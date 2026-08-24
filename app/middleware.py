from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from flask import Flask, g, request

from app.playback.providers import (
    ID_CATALOG_EMBED_PROVIDER_SPECS,
    INDEXED_EMBED_PROVIDER_SPECS,
    validate_indexed_embed_url_template,
)

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
        media_sources = ["'self'"]
        worker_sources = ["'self'"]
        if request.endpoint in {"youtube.detail", "reading.detail", "personal_tv.index"}:
            frame_sources.extend(("https://www.youtube-nocookie.com", "https://www.youtube.com"))
        if request.endpoint in {"youtube.detail", "personal_tv.index"}:
            script_sources.append("https://www.youtube.com")
        if request.endpoint == "mytv.index":
            script_sources.append("https://cdn.jsdelivr.net")
            # hls.js attaches its MediaSource through an in-memory blob URL.
            # Keep this permission scoped to IPTV instead of weakening media
            # policy for every page.
            media_sources.append("blob:")
            # hls.js also creates its demuxing worker from an in-memory blob.
            worker_sources.append("blob:")
        if app.config.get("DRAGON_VIDSRC_ENABLED"):
            parsed = urlsplit(str(app.config.get("DRAGON_VIDSRC_EMBED_URL") or ""))
            try:
                _port = parsed.port
            except ValueError:
                invalid_port = True
            else:
                invalid_port = False
            if (
                parsed.scheme == "https"
                and parsed.netloc
                and not parsed.username
                and not parsed.password
                and not invalid_port
                and _port != 0
            ):
                frame_sources.append(f"{parsed.scheme}://{parsed.netloc}")
                frame_sources.extend(VIDSRC_REDIRECT_HOSTS.get(parsed.hostname or "", ()))
        for provider_spec in ID_CATALOG_EMBED_PROVIDER_SPECS:
            if app.config.get(f"DRAGON_{provider_spec.key.upper()}_ENABLED"):
                frame_sources.extend(
                    f"https://{domain}" for domain in sorted(provider_spec.allowed_domains)
                )
        for provider_spec in INDEXED_EMBED_PROVIDER_SPECS:
            provider_key = provider_spec.key.upper()
            if not app.config.get(f"DRAGON_{provider_key}_ENABLED"):
                continue
            template = str(app.config.get(f"DRAGON_{provider_key}_EMBED_URL") or "")
            try:
                template = validate_indexed_embed_url_template(provider_spec.key, template)
            except ValueError:
                continue
            parsed = urlsplit(template)
            try:
                _port = parsed.port
            except ValueError:
                continue
            if (
                parsed.scheme == "https"
                and parsed.netloc
                and not parsed.username
                and not parsed.password
                and _port != 0
            ):
                frame_sources.append(f"{parsed.scheme}://{parsed.netloc}")
        if (
            request.endpoint == "movies.detail"
            and app.config.get("DRAGON_PLAYBACK_ENABLED")
            and app.config.get("DRAGON_MAGNETS_ENABLED")
        ):
            media_sources.append("http://127.0.0.1:*")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src {' '.join(script_sources)}; "
            "style-src 'self'; "
            "font-src 'self'; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            f"media-src {' '.join(media_sources)}; "
            f"worker-src {' '.join(worker_sources)}; "
            f"frame-src {' '.join(frame_sources)}; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response
