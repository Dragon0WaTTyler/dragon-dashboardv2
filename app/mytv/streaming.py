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


def _mp4_box_header(data: bytes | bytearray, offset: int = 0) -> tuple[int, int] | None:
    """Return an ISO-BMFF box's total size and header size when its header is complete."""
    if len(data) - offset < 8:
        return None
    size = int.from_bytes(data[offset : offset + 4], "big")
    if size == 1:
        if len(data) - offset < 16:
            return None
        size = int.from_bytes(data[offset + 8 : offset + 16], "big")
        return (size, 16) if size >= 16 else None
    return (size, 8) if size >= 8 else None


def _iter_mp4_boxes(data: bytes, start: int, end: int):
    offset = start
    while offset < end:
        header = _mp4_box_header(data, offset)
        if header is None:
            return
        size, header_size = header
        box_end = offset + size
        if size == 0 or box_end > end:
            return
        yield data[offset + 4 : offset + 8], offset + header_size, box_end
        offset = box_end


def _fragment_decode_times(moof: bytes) -> dict[int, int]:
    """Read each track's tfdt timestamp from one fragmented-MP4 moof box."""
    root = _mp4_box_header(moof)
    if root is None:
        return {}
    _, root_header_size = root
    decode_times: dict[int, int] = {}
    for box_type, traf_start, traf_end in _iter_mp4_boxes(moof, root_header_size, len(moof)):
        if box_type != b"traf":
            continue
        track_id = None
        decode_time = None
        for child_type, child_start, child_end in _iter_mp4_boxes(moof, traf_start, traf_end):
            payload = moof[child_start:child_end]
            if child_type == b"tfhd" and len(payload) >= 8:
                track_id = int.from_bytes(payload[4:8], "big")
            elif child_type == b"tfdt" and len(payload) >= 8:
                version = payload[0]
                if version == 1 and len(payload) >= 12:
                    decode_time = int.from_bytes(payload[4:12], "big")
                elif version == 0:
                    decode_time = int.from_bytes(payload[4:8], "big")
        if track_id is not None and decode_time is not None:
            decode_times[track_id] = decode_time
    return decode_times


class _FragmentDeduplicator:
    """Suppress replayed fMP4 fragments after an IPTV input reconnects."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._last_decode_times: dict[int, int] = {}
        self._discard_fragment = False
        self._media_remaining = 0
        self._discard_media = False

    def _is_replayed_fragment(self, decode_times: dict[int, int]) -> bool:
        known = [
            (track_id, timestamp)
            for track_id, timestamp in decode_times.items()
            if track_id in self._last_decode_times
        ]
        return bool(known) and len(known) == len(decode_times) and all(
            timestamp <= self._last_decode_times[track_id]
            for track_id, timestamp in known
        )

    def _remember_fragment(self, decode_times: dict[int, int]) -> None:
        for track_id, timestamp in decode_times.items():
            self._last_decode_times[track_id] = max(
                timestamp, self._last_decode_times.get(track_id, timestamp)
            )

    def feed(self, chunk: bytes) -> bytes:
        self._buffer.extend(chunk)
        output = bytearray()
        while True:
            if self._media_remaining:
                available = min(self._media_remaining, len(self._buffer))
                if not available:
                    break
                media = bytes(self._buffer[:available])
                del self._buffer[:available]
                self._media_remaining -= available
                if not self._discard_media:
                    output.extend(media)
                if self._media_remaining == 0:
                    self._discard_fragment = False
                    self._discard_media = False
                continue

            header = _mp4_box_header(self._buffer)
            if header is None:
                break
            size, header_size = header
            if size == 0:
                output.extend(self._buffer)
                self._buffer.clear()
                break
            box_type = bytes(self._buffer[4:8])
            if box_type == b"mdat":
                del self._buffer[:header_size]
                self._media_remaining = size - header_size
                self._discard_media = self._discard_fragment
                if not self._discard_media:
                    output.extend(size.to_bytes(4, "big") + box_type)
                if self._media_remaining == 0:
                    self._discard_fragment = False
                    self._discard_media = False
                continue
            if len(self._buffer) < size:
                break
            box = bytes(self._buffer[:size])
            del self._buffer[:size]
            if box_type == b"moof":
                decode_times = _fragment_decode_times(box)
                self._discard_fragment = self._is_replayed_fragment(decode_times)
                if not self._discard_fragment:
                    self._remember_fragment(decode_times)
                    output.extend(box)
            elif not self._discard_fragment:
                output.extend(box)
        return bytes(output)

    def flush(self) -> bytes:
        if self._discard_fragment or self._discard_media:
            return b""
        remaining = bytes(self._buffer)
        self._buffer.clear()
        return remaining


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

    startup_queue: queue.Queue[bytes | BaseException] = queue.Queue(maxsize=1)

    def read_startup_fragment() -> None:
        buffered = bytearray()
        try:
            while process.stdout:
                chunk = process.stdout.read(64 * 1024)
                if not chunk:
                    startup_queue.put(bytes(buffered))
                    return
                buffered.extend(chunk)
                # FFmpeg can emit a valid fMP4 header before it decodes any media.
                # Do not report a channel as playable until its first media fragment
                # is present; otherwise dead HLS manifests look like a 200 response.
                if b"moof" in buffered and b"mdat" in buffered:
                    startup_queue.put(bytes(buffered))
                    return
        except BaseException as error:  # pragma: no cover - defensive pipe failure
            startup_queue.put(error)

    threading.Thread(
        target=read_startup_fragment,
        daemon=True,
        name="dragon-tv-stream-start",
    ).start()
    try:
        first_chunk = startup_queue.get(timeout=STREAM_START_TIMEOUT_SECONDS)
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
    if not first_chunk or b"moof" not in first_chunk or b"mdat" not in first_chunk:
        _stop_process(process)
        _transcode_slots.release()
        raise StreamUnavailable("The channel source did not produce playable video.")

    cleanup_lock = threading.Lock()
    cleaned_up = False

    def cleanup() -> None:
        nonlocal cleaned_up
        with cleanup_lock:
            if cleaned_up:
                return
            cleaned_up = True
        _stop_process(process)
        _transcode_slots.release()

    @stream_with_context
    def generate():
        deduplicator = _FragmentDeduplicator()
        try:
            initial_output = deduplicator.feed(first_chunk)
            if initial_output:
                yield initial_output
            while process.stdout:
                chunk = process.stdout.read(64 * 1024)
                if not chunk:
                    break
                output = deduplicator.feed(chunk)
                if output:
                    yield output
            final_output = deduplicator.flush()
            if final_output:
                yield final_output
        finally:
            cleanup()

    response = Response(
        generate(),
        content_type="video/mp4",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        direct_passthrough=True,
    )
    response.call_on_close(cleanup)
    return response


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
