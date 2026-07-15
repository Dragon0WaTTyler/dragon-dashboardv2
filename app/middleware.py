from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from flask import Flask, g, request

VIDSRC_REDIRECT_HOSTS = {
    "v2.vidsrc.me": ("https://vidsrc.me", "https://vidsrcme.ru"),
}


def install_request_middleware(app: Flask) -> None:
    @app.before_request
    def assign_request_id() -> None:
        g.request_id = f"req_{uuid.uuid4().hex}"

    @app.after_request
    def secure_response(response):
        request_id = getattr(g, "request_id", f"req_{uuid.uuid4().hex}")
        g.request_id = request_id
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        frame_sources = ["'self'"]
        script_sources = ["'self'"]
        if request.endpoint == "youtube.detail":
            frame_sources.extend(
                ("https://www.youtube-nocookie.com", "https://www.youtube.com")
            )
            script_sources.append("https://www.youtube.com")
        if app.config.get("DRAGON_VIDSRC_ENABLED"):
            parsed = urlsplit(str(app.config.get("DRAGON_VIDSRC_EMBED_URL") or ""))
            if parsed.scheme == "https" and parsed.netloc:
                frame_sources.append(f"{parsed.scheme}://{parsed.netloc}")
                frame_sources.extend(VIDSRC_REDIRECT_HOSTS.get(parsed.hostname or "", ()))
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src {' '.join(script_sources)}; "
            "style-src 'self'; "
            "font-src 'self'; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            f"frame-src {' '.join(frame_sources)}; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response
