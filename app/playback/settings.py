from __future__ import annotations

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.playback.providers import (
    INDEXED_EMBED_PROVIDER_SPECS,
    build_provider_registry_from_config,
)
from app.playback.services import PlaybackService

bp = Blueprint("playback_settings", __name__, url_prefix="/settings/playback")


def _configured_providers() -> list[dict]:
    registry = build_provider_registry_from_config(current_app.config)
    provider_keys: list[str] = []
    if current_app.config.get("DRAGON_PLAYBACK_ENABLED") and current_app.config.get(
        "DRAGON_VIDSRC_ENABLED"
    ):
        provider_keys.append("vidsrc")
    if current_app.config.get("DRAGON_PLAYBACK_ENABLED"):
        provider_keys.extend(
            spec.key
            for spec in INDEXED_EMBED_PROVIDER_SPECS
            if current_app.config.get(f"DRAGON_{spec.key.upper()}_ENABLED")
        )
    preferences = PlaybackService.provider_preferences(frozenset(provider_keys))
    return [
        {
            "key": key,
            "label": registry.require(key).display_name if key != "vidsrc" else "VidSrc",
            **preferences[key],
        }
        for key in provider_keys
    ]


@bp.get("")
@login_required
def index():
    return render_template(
        "playback/settings.html",
        active_module="more",
        providers=_configured_providers(),
    )


@bp.post("/providers/<provider>")
@login_required
def update_provider(provider: str):
    configured = {item["key"] for item in _configured_providers()}
    if provider not in configured:
        abort(404)
    try:
        priority = int(str(request.form.get("priority") or "100"))
    except ValueError:
        flash("Provider priority must be a whole number.", "error")
        return redirect(url_for("playback_settings.index"))
    PlaybackService.save_provider_preference(
        provider=provider,
        enabled=request.form.get("enabled") == "on",
        priority=priority,
        background_checks=request.form.get("background_checks") == "on",
    )
    flash("Playback provider preference saved.", "success")
    return redirect(url_for("playback_settings.index"))
