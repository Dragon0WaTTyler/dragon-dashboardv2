from __future__ import annotations

import uuid

from flask import Flask, g


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
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "font-src 'self'; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response
