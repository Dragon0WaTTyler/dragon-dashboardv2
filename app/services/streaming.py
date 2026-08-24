from __future__ import annotations

import ipaddress
import queue
import re
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from flask import Response, current_app, request, stream_with_context, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer

URI_ATTRIBUTE_RE = re.compile(r'URI="([^"]+)"')
UPSTREAM_OPEN_ATTEMPTS = 3
RETRYABLE_UPSTREAM_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_transcode_lock = threading.Lock()
_transcode_semaphore: threading.BoundedSemaphore | None = None
_transcode_limit = 0
TRANSCODE_START_TIMEOUT_SECONDS = 12


class UnsafeStreamUrl(ValueError):
    pass


@lru_cache(maxsize=1024)
def _resolved_addresses(hostname: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                item[4][0]
                for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
            }
        )
    )


def validate_stream_url(url: str, *, allow_private: bool = False) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeStreamUrl("Only HTTP(S) stream URLs are supported")
    if allow_private or current_app.config.get("MYTV_ALLOW_PRIVATE_STREAMS"):
        return url
    try:
        addresses = _resolved_addresses(parsed.hostname)
    except socket.gaierror as error:
        raise UnsafeStreamUrl("The stream host could not be resolved") from error
    if not addresses:
        raise UnsafeStreamUrl("The stream host has no address")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise UnsafeStreamUrl("Private and reserved stream hosts are blocked")
    return url


def _open_upstream(
    url: str,
    *,
    allow_private: bool = False,
    extra_headers: dict[str, str] | None = None,
) -> tuple[requests.Response, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (My TV Dashboard)",
        "Accept": request.headers.get("Accept", "*/*"),
    }
    headers.update(extra_headers or {})
    if request.headers.get("Range"):
        headers["Range"] = request.headers["Range"]

    connect_timeout = max(1, int(current_app.config.get("MYTV_HTTP_TIMEOUT", 15)))
    last_error: requests.RequestException | None = None
    for attempt in range(UPSTREAM_OPEN_ATTEMPTS):
        current_url = url
        try:
            for _ in range(4):
                validate_stream_url(current_url, allow_private=allow_private)
                response = requests.get(
                    current_url,
                    headers=headers,
                    stream=True,
                    allow_redirects=False,
                    timeout=(connect_timeout, 45),
                )
                if response.status_code not in {301, 302, 303, 307, 308}:
                    if (
                        response.status_code in RETRYABLE_UPSTREAM_STATUS_CODES
                        and attempt < UPSTREAM_OPEN_ATTEMPTS - 1
                    ):
                        response.close()
                        time.sleep(0.25 * (attempt + 1))
                        break
                    return response, current_url
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise requests.RequestException(
                        "Stream redirect did not include a location"
                    )
                current_url = urljoin(current_url, location)
            else:
                raise requests.TooManyRedirects("The stream redirected too many times")
        except (requests.RequestException, OSError) as error:
            last_error = error
            if attempt == UPSTREAM_OPEN_ATTEMPTS - 1:
                raise
            time.sleep(0.25 * (attempt + 1))
    if last_error is not None:  # pragma: no cover - loop exits through raise/return
        raise last_error
    raise requests.RequestException("The stream could not be opened")


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.secret_key, salt="mytv-hls-resource")


def make_resource_token(url: str) -> str:
    return _serializer().dumps(url)


def read_resource_token(token: str) -> str:
    try:
        return _serializer().loads(token, max_age=60 * 60 * 6)
    except BadSignature as error:
        raise UnsafeStreamUrl("The playback link is invalid or expired") from error


def rewrite_hls_manifest(text: str, manifest_url: str) -> str:
    output: list[str] = []

    def proxy_url(candidate: str) -> str:
        absolute = urljoin(manifest_url, candidate)
        token = make_resource_token(absolute)
        return url_for("mytv.hls_resource", token=token, _external=False)

    # Never discard or renumber a provider's live segments here. HLS clients
    # use the exact media sequence and discontinuity history to merge reloads;
    # rewriting only the URLs keeps that state intact during long playback.
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            output.append(line)
        elif stripped.startswith("#"):
            output.append(
                URI_ATTRIBUTE_RE.sub(
                    lambda match: f'URI="{proxy_url(match.group(1))}"', line
                )
            )
        else:
            output.append(proxy_url(stripped))
    return "\n".join(output) + "\n"


def proxy_stream(
    url: str,
    force_manifest: bool = False,
    *,
    allow_private: bool = False,
    extra_headers: dict[str, str] | None = None,
) -> Response:
    upstream, final_url = _open_upstream(
        url,
        allow_private=allow_private,
        extra_headers=extra_headers,
    )
    content_type = upstream.headers.get("Content-Type", "application/octet-stream")
    is_manifest = force_manifest or "mpegurl" in content_type.lower() or final_url.lower().split("?", 1)[0].endswith((".m3u8", ".m3u"))

    if is_manifest:
        try:
            body = upstream.content.decode(upstream.encoding or "utf-8-sig", "replace")
        finally:
            upstream.close()
        return Response(
            rewrite_hls_manifest(body, final_url),
            status=upstream.status_code,
            content_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-store"},
        )

    allowed_headers = {}
    for name in ("Content-Length", "Content-Range", "Accept-Ranges", "ETag"):
        if name in upstream.headers:
            allowed_headers[name] = upstream.headers[name]
    allowed_headers["Cache-Control"] = "no-store"
    allowed_headers["X-Accel-Buffering"] = "no"

    @stream_with_context
    def generate():
        try:
            yield from upstream.iter_content(chunk_size=64 * 1024)
        finally:
            upstream.close()

    return Response(
        generate(),
        status=upstream.status_code,
        content_type=content_type,
        headers=allowed_headers,
        direct_passthrough=True,
    )


def transcode_stream(
    source: str | Path,
    *,
    allow_private: bool = False,
    input_headers: dict[str, str] | None = None,
    start_seconds: float | None = None,
    on_failure: Callable[[str], None] | None = None,
) -> Response:
    is_local_file = isinstance(source, Path)
    if is_local_file:
        input_value = str(source.resolve())
        if not source.is_file():
            message = "The completed cached video file is unavailable."
            _notify_transcode_failure(on_failure, message)
            return Response(message, status=404, content_type="text/plain")
    else:
        input_value = validate_stream_url(str(source), allow_private=allow_private)
    ffmpeg = shutil.which(current_app.config.get("MYTV_FFMPEG", "ffmpeg"))
    if not ffmpeg:
        message = "FFmpeg is required for this stream format."
        _notify_transcode_failure(on_failure, message)
        return Response(message, status=503, content_type="text/plain")

    semaphore = _get_transcode_semaphore(current_app.config.get("MYTV_MAX_TRANSCODES", 2))
    if not semaphore.acquire(blocking=False):
        return Response(
            "All transcoding slots are busy. Try another channel in a moment.",
            status=429,
            content_type="text/plain",
            headers={"Retry-After": "5"},
        )

    serialized_headers = ""
    if input_headers:
        serialized_headers = "".join(
            f"{name}: {value}\r\n" for name, value in input_headers.items() if value
        )

    command = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-analyzeduration",
        "15000000",
        "-probesize",
        "50000000",
    ]
    if not is_local_file:
        command.extend(["-rw_timeout", "15000000"])
    if start_seconds is not None and start_seconds > 0:
        command.extend(["-ss", f"{float(start_seconds):.3f}"])
    if serialized_headers and not is_local_file:
        command.extend(["-headers", serialized_headers])
    if not is_local_file:
        command.extend([
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "2",
        ])
    command.extend([
        "-i",
        input_value,
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0?",
        "-sn",
        "-dn",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-pix_fmt",
        "yuv420p",
        "-g",
        "48",
        "-keyint_min",
        "48",
        "-sc_threshold",
        "0",
        "-c:a",
        "aac",
        "-ac",
        "2",
        "-ar",
        "48000",
        "-b:a",
        "128k",
        "-movflags",
        "frag_keyframe+empty_moov+default_base_moof",
        # The MP4 muxer otherwise buffers packets while writing to a pipe.  That
        # leaves HEVC/x265 local playback showing a black frame even though the
        # torrent and FFmpeg process are both healthy.
        "-flush_packets",
        "1",
        "-frag_duration",
        "1000000",
        "-f",
        "mp4",
        "pipe:1",
    ])
    try:
        process = subprocess.Popen(  # noqa: S603 - ffmpeg path is resolved locally
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
    except OSError:
        semaphore.release()
        message = "FFmpeg could not start local transcoding."
        _notify_transcode_failure(on_failure, message)
        return Response(message, status=503, content_type="text/plain")

    stderr_buffer = bytearray()

    def read_stderr() -> None:
        stderr = getattr(process, "stderr", None)
        if stderr is None:
            return
        try:
            while chunk := stderr.read(4096):
                remaining = 16 * 1024 - len(stderr_buffer)
                if remaining > 0:
                    stderr_buffer.extend(chunk[:remaining])
        except OSError:
            return

    stderr_thread = threading.Thread(
        target=read_stderr,
        daemon=True,
        name="dragon-playback-transcode-errors",
    )
    stderr_thread.start()

    # Do not return a successful media response until FFmpeg has produced an
    # MP4 byte.  Previously an immediately failing/blocked transcode looked
    # like a valid 200 stream to the <video> element and resulted in a black
    # screen with no actionable error.
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
        name="dragon-playback-transcode-start",
    ).start()
    try:
        first_chunk = first_chunk_queue.get(timeout=TRANSCODE_START_TIMEOUT_SECONDS)
    except queue.Empty:
        _stop_transcode_process(process)
        stderr_thread.join(timeout=0.5)
        semaphore.release()
        message = _transcode_failure_message(
            stderr_buffer,
            fallback="Local transcoding did not produce video within 12 seconds.",
        )
        _notify_transcode_failure(on_failure, message)
        return Response(message, status=504, content_type="text/plain")
    if isinstance(first_chunk, BaseException) or not first_chunk:
        _stop_transcode_process(process)
        stderr_thread.join(timeout=0.5)
        semaphore.release()
        message = _transcode_failure_message(
            stderr_buffer,
            fallback="Local transcoding failed before video could start.",
        )
        _notify_transcode_failure(on_failure, message)
        return Response(message, status=503, content_type="text/plain")

    @stream_with_context
    def generate():
        reached_eof = False
        return_code = None
        try:
            yield first_chunk
            while process.stdout:
                chunk = process.stdout.read(64 * 1024)
                if not chunk:
                    reached_eof = True
                    break
                yield chunk
        finally:
            if reached_eof:
                try:
                    return_code = process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    _stop_transcode_process(process)
                    return_code = process.poll()
            else:
                _stop_transcode_process(process)
            stderr_thread.join(timeout=0.5)
            semaphore.release()
            if reached_eof and return_code not in {None, 0}:
                message = _transcode_failure_message(
                    stderr_buffer,
                    fallback="Local transcoding stopped unexpectedly.",
                )
                _notify_transcode_failure(on_failure, message)

    return Response(
        generate(),
        content_type="video/mp4",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
        direct_passthrough=True,
    )


def _notify_transcode_failure(
    callback: Callable[[str], None] | None,
    message: str,
) -> None:
    current_app.logger.warning("Local transcode failure: %s", message)
    if callback is not None:
        callback(message)


def _transcode_failure_message(stderr: bytearray, *, fallback: str) -> str:
    detail = bytes(stderr).decode("utf-8", "replace").casefold()
    if "connection refused" in detail or "server returned 4" in detail:
        return "The local torrent stream rejected the transcoder connection."
    if "invalid data found" in detail or "error opening input" in detail:
        return "FFmpeg could not read this release. The cached file may be incomplete."
    if "no such file" in detail:
        return "The completed cached video file is unavailable."
    if "decoder" in detail or "decode" in detail:
        return "FFmpeg could not decode this release's video stream."
    if "encoder" in detail or "libx264" in detail:
        return "FFmpeg could not start the browser-compatible video encoder."
    return fallback


def _stop_transcode_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()


def _get_transcode_semaphore(limit: int) -> threading.BoundedSemaphore:
    global _transcode_limit, _transcode_semaphore
    limit = max(1, int(limit))
    with _transcode_lock:
        if _transcode_semaphore is None or _transcode_limit != limit:
            _transcode_limit = limit
            _transcode_semaphore = threading.BoundedSemaphore(limit)
    return _transcode_semaphore
