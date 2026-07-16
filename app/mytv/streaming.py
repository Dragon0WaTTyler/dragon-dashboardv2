from __future__ import annotations

import hashlib
import ipaddress
import queue
import shutil
import socket
import subprocess
import threading
import time
from functools import lru_cache
from urllib.parse import urljoin, urlsplit

import requests
from flask import Response, request, stream_with_context

TRANSCODE_LIMIT = 2
STREAM_START_TIMEOUT_SECONDS = 12
STREAM_FAILURE_TTL_SECONDS = 15 * 60
_transcode_slots = threading.BoundedSemaphore(TRANSCODE_LIMIT)
_stream_failures: dict[bytes, float] = {}
_stream_failures_lock = threading.Lock()


class StreamUnavailable(RuntimeError):
    pass


def _stream_key(url: str) -> bytes:
    return hashlib.sha256(url.encode("utf-8", "ignore")).digest()


def stream_failure_penalty(url: str) -> int:
    key = _stream_key(url)
    now = time.monotonic()
    with _stream_failures_lock:
        expires_at = _stream_failures.get(key, 0)
        if expires_at <= now:
            _stream_failures.pop(key, None)
            return 0
        return 1


def mark_stream_failure(url: str) -> None:
    with _stream_failures_lock:
        _stream_failures[_stream_key(url)] = (
            time.monotonic() + STREAM_FAILURE_TTL_SECONDS
        )


def mark_stream_success(url: str) -> None:
    with _stream_failures_lock:
        _stream_failures.pop(_stream_key(url), None)


@lru_cache(maxsize=1024)
def _resolve(hostname: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                item[4][0]
                for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
            }
        )
    )


def validate_stream_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise StreamUnavailable("Only HTTP(S) streams are supported.")
    try:
        addresses = _resolve(parsed.hostname)
    except OSError as error:
        raise StreamUnavailable("The stream host could not be resolved.") from error
    if not addresses or any(not ipaddress.ip_address(item).is_global for item in addresses):
        raise StreamUnavailable("Private and reserved stream hosts are blocked.")
    return url


def _open_upstream(url: str) -> requests.Response:
    headers = {
        "User-Agent": "Mozilla/5.0 (Dragon My TV)",
        "Accept": request.headers.get("Accept", "*/*"),
    }
    if request.headers.get("Range"):
        headers["Range"] = request.headers["Range"]
    current = url
    for _ in range(4):
        validate_stream_url(current)
        response = requests.get(
            current,
            headers=headers,
            stream=True,
            allow_redirects=False,
            timeout=(15, 45),
        )
        if response.status_code not in {301, 302, 303, 307, 308}:
            if response.status_code == 204 or response.status_code >= 400:
                status_code = response.status_code
                response.close()
                raise StreamUnavailable(
                    f"The channel source returned HTTP {status_code}."
                )
            return response
        location = response.headers.get("Location")
        response.close()
        if not location:
            raise StreamUnavailable("The stream redirected without a location.")
        current = urljoin(current, location)
    raise StreamUnavailable("The stream redirected too many times.")


def proxy_file(url: str) -> Response:
    upstream = _open_upstream(url)
    headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    for name in ("Content-Length", "Content-Range", "Accept-Ranges", "ETag"):
        if name in upstream.headers:
            headers[name] = upstream.headers[name]

    @stream_with_context
    def generate():
        try:
            yield from upstream.iter_content(chunk_size=64 * 1024)
        finally:
            upstream.close()

    return Response(
        generate(),
        status=upstream.status_code,
        content_type=upstream.headers.get("Content-Type", "video/mp4"),
        headers=headers,
        direct_passthrough=True,
    )


def transcode_stream(url: str) -> Response:
    validate_stream_url(url)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise StreamUnavailable("FFmpeg is required for this channel format.")
    if not _transcode_slots.acquire(blocking=False):
        return Response(
            "All TV playback slots are busy. Try again in a moment.",
            status=429,
            content_type="text/plain",
            headers={"Retry-After": "5"},
        )
    command = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-rw_timeout",
        "15000000",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_delay_max",
        "2",
        "-user_agent",
        "Mozilla/5.0 (Dragon My TV)",
        "-analyzeduration",
        "2000000",
        "-probesize",
        "2000000",
        "-i",
        url,
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "frag_keyframe+empty_moov+default_base_moof",
        "-flush_packets",
        "1",
        "-f",
        "mp4",
        "pipe:1",
    ]
    try:
        process = subprocess.Popen(  # noqa: S603 - executable path is resolved locally
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
    except Exception:
        _transcode_slots.release()
        raise

    first_chunk_queue: queue.Queue[bytes | BaseException] = queue.Queue(maxsize=1)

    def read_first_chunk() -> None:
        try:
            chunk = process.stdout.read(64 * 1024) if process.stdout else b""
            first_chunk_queue.put(chunk)
        except BaseException as error:  # pragma: no cover - defensive pipe failure
            first_chunk_queue.put(error)

    threading.Thread(
        target=read_first_chunk,
        daemon=True,
        name="dragon-tv-stream-start",
    ).start()
    try:
        first_chunk = first_chunk_queue.get(timeout=STREAM_START_TIMEOUT_SECONDS)
    except queue.Empty as error:
        _stop_process(process)
        _transcode_slots.release()
        raise StreamUnavailable(
            "This channel did not send video within 12 seconds."
        ) from error
    if isinstance(first_chunk, BaseException):
        _stop_process(process)
        _transcode_slots.release()
        raise StreamUnavailable("The channel stream could not be read.") from first_chunk
    if not first_chunk:
        _stop_process(process)
        _transcode_slots.release()
        raise StreamUnavailable("The channel source is offline or rejected playback.")

    @stream_with_context
    def generate():
        try:
            yield first_chunk
            while process.stdout:
                chunk = process.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            _stop_process(process)
            _transcode_slots.release()

    return Response(
        generate(),
        content_type="video/mp4",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        direct_passthrough=True,
    )


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
