from __future__ import annotations

import ipaddress
import re
import shutil
import socket
import subprocess
import threading
from functools import lru_cache
from urllib.parse import urljoin, urlparse

import requests
from flask import Response, current_app, request, stream_with_context, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer


URI_ATTRIBUTE_RE = re.compile(r'URI="([^"]+)"')
_transcode_lock = threading.Lock()
_transcode_semaphore: threading.BoundedSemaphore | None = None
_transcode_limit = 0


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

    current_url = url
    for _ in range(4):
        validate_stream_url(current_url, allow_private=allow_private)
        response = requests.get(
            current_url,
            headers=headers,
            stream=True,
            allow_redirects=False,
            timeout=(current_app.config["MYTV_HTTP_TIMEOUT"], 45),
        )
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response, current_url
        location = response.headers.get("Location")
        response.close()
        if not location:
            raise requests.RequestException("Stream redirect did not include a location")
        current_url = urljoin(current_url, location)
    raise requests.TooManyRedirects("The stream redirected too many times")


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
    url: str,
    *,
    allow_private: bool = False,
    input_headers: dict[str, str] | None = None,
) -> Response:
    validate_stream_url(url, allow_private=allow_private)
    ffmpeg = shutil.which(current_app.config.get("MYTV_FFMPEG", "ffmpeg"))
    if not ffmpeg:
        return Response(
            "FFmpeg is required for this stream format.", status=503, content_type="text/plain"
        )

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
        "-rw_timeout",
        "15000000",
        "-analyzeduration",
        "15000000",
        "-probesize",
        "50000000",
    ]
    if serialized_headers:
        command.extend(["-headers", serialized_headers])
    command.extend([
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_delay_max",
        "2",
        "-i",
        url,
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
        "-f",
        "mp4",
        "pipe:1",
    ])
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )

    @stream_with_context
    def generate():
        try:
            while process.stdout:
                chunk = process.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
            semaphore.release()

    return Response(
        generate(),
        content_type="video/mp4",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
        direct_passthrough=True,
    )


def _get_transcode_semaphore(limit: int) -> threading.BoundedSemaphore:
    global _transcode_limit, _transcode_semaphore
    limit = max(1, int(limit))
    with _transcode_lock:
        if _transcode_semaphore is None or _transcode_limit != limit:
            _transcode_limit = limit
            _transcode_semaphore = threading.BoundedSemaphore(limit)
    return _transcode_semaphore
