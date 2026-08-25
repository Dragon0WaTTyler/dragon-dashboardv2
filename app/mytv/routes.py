from __future__ import annotations

import hashlib
import math
import secrets
import threading
from datetime import datetime, timedelta, timezone

import click
import requests
from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request
from flask_login import login_required
from sqlalchemy import case, delete, func, not_, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.extensions import db
from app.mytv.cache import query_cache
from app.mytv.epg import (
    EPGSyncService,
    epg_coordinator,
    now_next_for_ids,
)
from app.mytv.epg import (
    status_payload as epg_status_payload,
)
from app.mytv.health import health_coordinator, record_channel_health
from app.mytv.models import (
    TVChannel,
    TVChannelHealth,
    TVChannelPreference,
    TVChannelRepresentative,
    TVGroup,
    TVPlaylist,
    TVSource,
    TVTheme,
)
from app.mytv.services import GithubTVSync, persist_theme_preference, sync_coordinator
from app.mytv.streaming import (
    STREAM_START_TIMEOUT_SECONDS,
    StreamUnavailable,
    mark_stream_failure,
    mark_stream_success,
    proxy_file,
    stream_failure_penalty,
    transcode_stream,
)
from app.services.streaming import UnsafeStreamUrl, proxy_stream, read_resource_token

bp = Blueprint("mytv", __name__, url_prefix="/iptv")
PLAYBACK_CANDIDATE_LIMIT = 3
_BULK_UNDO_TTL = timedelta(seconds=20)
_bulk_undo_lock = threading.Lock()
_bulk_undo: dict[str, dict] = {}


def _effective_enabled():
    return func.coalesce(TVChannel.enabled_override, TVTheme.channel_policy, TVTheme.enabled).is_(
        True
    )


def _cache_key(namespace: str, *parts: object) -> str:
    database = db.engine.url.render_as_string(hide_password=True)
    return ":".join((database, namespace, *(str(part) for part in parts)))


def _json_cache_response(payload: dict, hit: bool):
    response = jsonify(payload)
    response.headers["X-MyTV-Cache"] = "HIT" if hit else "MISS"
    response.headers["X-MyTV-Cache-Generation"] = str(query_cache.generation)
    response.headers["Cache-Control"] = "private, max-age=0, must-revalidate"
    return response


def _health_payload() -> dict:
    counts = {
        str(status): int(count)
        for status, count in db.session.execute(
            select(TVChannelHealth.status, func.count(TVChannelHealth.preference_key)).group_by(
                TVChannelHealth.status
            )
        )
    }
    latest = db.session.scalar(select(func.max(TVChannelHealth.checked_at)))
    if latest is not None and latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    checked = counts.get("online", 0) + counts.get("offline", 0)
    return {
        **health_coordinator.status(),
        "checked": checked,
        "known_online": counts.get("online", 0),
        "known_offline": counts.get("offline", 0),
        "last_checked_at": latest.isoformat() if latest else None,
        "needs_check": checked == 0
        or latest is None
        or latest < datetime.now(timezone.utc) - timedelta(hours=10),
    }


def _last_channel_payload() -> dict | None:
    row = db.session.execute(
        select(TVChannel, TVChannelPreference.last_watched_at, TVTheme.name.label("theme_name"))
        .join(
            TVChannelRepresentative,
            TVChannelRepresentative.channel_id == TVChannel.id,
        )
        .join(
            TVChannelPreference,
            TVChannelPreference.preference_key == TVChannel.preference_key,
        )
        .join(TVGroup, TVGroup.id == TVChannel.group_id)
        .join(TVTheme, TVTheme.id == TVGroup.theme_id)
        .where(TVChannelPreference.last_watched_at.is_not(None))
        .order_by(TVChannelPreference.last_watched_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    channel = row[0]
    watched_at = row.last_watched_at
    if watched_at is not None and watched_at.tzinfo is None:
        watched_at = watched_at.replace(tzinfo=timezone.utc)
    return {
        "id": channel.id,
        "name": channel.name,
        "logo_url": channel.logo_url,
        "group_name": row.theme_name,
        "last_watched_at": watched_at.isoformat() if watched_at else None,
    }


@bp.get("")
@login_required
def index():
    from app.admin.control_center import preference_store

    preferences = preference_store().read()["sections"]["mytv"]
    source_repo = db.session.scalar(
        select(TVSource.locator).where(TVSource.protected.is_(True))
    ) or "Dragon0WaTTyler/Dragon-IPTV-Clean"
    return render_template(
        "mytv/index.html",
        active_module="mytv",
        source_repo=source_repo,
        favorites_first=preferences["favorites_first"],
        default_view=preferences["default_view"],
        default_sort=preferences["default_sort"],
    )


@bp.get("/api/bootstrap")
@login_required
def bootstrap():
    def build_payload() -> dict:
        effective = _effective_enabled()
        total_channels = int(
            db.session.scalar(
                select(func.count(TVChannelRepresentative.channel_id))
                .outerjoin(
                    TVChannelHealth,
                    TVChannelHealth.preference_key == TVChannelRepresentative.preference_key,
                )
                .where(
                    or_(
                        TVChannelHealth.status.is_(None),
                        TVChannelHealth.status != "offline",
                    )
                )
            )
            or 0
        )
        enabled_channels = int(
            db.session.scalar(
                select(func.count(TVChannelRepresentative.channel_id))
                .join(
                    TVChannel,
                    TVChannel.id == TVChannelRepresentative.channel_id,
                )
                .join(TVGroup, TVGroup.id == TVChannel.group_id)
                .join(TVTheme, TVTheme.id == TVGroup.theme_id)
                .join(TVPlaylist, TVPlaylist.id == TVChannel.playlist_id)
                .outerjoin(
                    TVChannelHealth,
                    TVChannelHealth.preference_key == TVChannel.preference_key,
                )
                .where(
                    TVPlaylist.imported.is_(True),
                    TVPlaylist.available.is_(True),
                    effective,
                    or_(
                        TVChannelHealth.status.is_(None),
                        TVChannelHealth.status != "offline",
                    ),
                )
            )
            or 0
        )
        theme_count = int(
            db.session.scalar(
                select(func.count(func.distinct(TVTheme.id)))
                .join(TVGroup, TVGroup.theme_id == TVTheme.id)
                .join(TVPlaylist, TVPlaylist.id == TVGroup.playlist_id)
                .where(
                    TVPlaylist.imported.is_(True),
                    TVPlaylist.available.is_(True),
                )
            )
            or 0
        )
        imported_sources = int(
            db.session.scalar(
                select(func.count(TVPlaylist.id)).where(
                    TVPlaylist.imported.is_(True),
                    TVPlaylist.available.is_(True),
                    TVPlaylist.enabled.is_(True),
                )
            )
            or 0
        )
        repo_files = int(
            db.session.scalar(
                select(func.count(TVPlaylist.id)).where(TVPlaylist.available.is_(True))
            )
            or 0
        )
        pending_files = int(
            db.session.scalar(
                select(func.count(TVPlaylist.id)).where(
                    TVPlaylist.available.is_(True), TVPlaylist.imported.is_(False)
                )
            )
            or 0
        )
        favorite_channels = int(
            db.session.scalar(
                select(func.count(TVChannelPreference.preference_key)).where(
                    TVChannelPreference.favorite.is_(True)
                )
            )
            or 0
        )
        return {
            "stats": {
                "total_channels": total_channels,
                "enabled_channels": enabled_channels,
                "groups": theme_count,
                "imported_playlists": imported_sources,
                "repo_files": repo_files,
                "pending_files": pending_files,
                "favorite_channels": favorite_channels,
            },
        }

    cached, hit = query_cache.get_or_set(_cache_key("bootstrap"), build_payload, ttl_seconds=60)
    return _json_cache_response(
        {
            **cached,
            "sync": sync_coordinator.status(),
            "health": _health_payload(),
            "epg": epg_status_payload(),
            "last_channel": _last_channel_payload(),
        },
        hit,
    )


@bp.get("/api/groups")
@login_required
def groups():
    playlist_id = request.args.get("playlist_id", type=int)
    query = str(request.args.get("q") or "").strip()
    active_only = request.args.get("active_only") == "1"
    visibility = str(request.args.get("visibility") or "all")
    if visibility not in {"all", "on", "off"}:
        abort(400, "visibility must be all, on, or off.")

    def build_payload() -> dict:
        conditions = [
            TVPlaylist.imported.is_(True),
            TVPlaylist.available.is_(True),
            TVPlaylist.enabled.is_(True),
        ]
        if playlist_id:
            conditions.append(TVGroup.playlist_id == playlist_id)
        if active_only:
            conditions.append(TVTheme.enabled.is_(True))
        if visibility == "on":
            conditions.append(TVTheme.enabled.is_(True))
        elif visibility == "off":
            conditions.append(TVTheme.enabled.is_(False))
        if query:
            search = f"%{query}%"
            conditions.append(or_(TVTheme.name.ilike(search), TVGroup.name.ilike(search)))

        statement = (
            select(
                TVTheme.id,
                TVTheme.key,
                TVTheme.name,
                TVTheme.enabled,
                TVTheme.channel_policy,
                func.count(func.distinct(TVGroup.id)).label("group_count"),
                func.count(func.distinct(TVPlaylist.id)).label("source_count"),
                func.group_concat(func.distinct(TVPlaylist.name)).label("source_names"),
                func.max(case((TVPlaylist.enabled.is_(True), 1), else_=0)).label(
                    "has_active_source"
                ),
            )
            .select_from(TVTheme)
            .join(TVGroup, TVGroup.theme_id == TVTheme.id)
            .join(TVPlaylist, TVPlaylist.id == TVGroup.playlist_id)
            .where(*conditions)
            .group_by(TVTheme.id)
            .order_by(TVTheme.position, TVTheme.name)
            .limit(1000)
        )
        rows = list(db.session.execute(statement))
        theme_ids = [int(row.id) for row in rows]
        channel_counts: dict[int, int] = {}
        if theme_ids:
            for count_theme_id, channel_count in db.session.execute(
                select(
                    TVGroup.theme_id,
                    func.count(TVChannelRepresentative.channel_id),
                )
                .join(TVChannel, TVChannel.id == TVChannelRepresentative.channel_id)
                .join(TVGroup, TVGroup.id == TVChannel.group_id)
                .join(TVPlaylist, TVPlaylist.id == TVChannel.playlist_id)
                .where(
                    TVGroup.theme_id.in_(theme_ids),
                    TVPlaylist.imported.is_(True),
                    TVPlaylist.available.is_(True),
                    TVPlaylist.enabled.is_(True),
                )
                .group_by(TVGroup.theme_id)
            ):
                channel_counts[int(count_theme_id)] = int(channel_count or 0)
        exceptions: dict[int, tuple[int, int]] = {}
        if theme_ids:
            exception_conditions = [
                TVGroup.theme_id.in_(theme_ids),
                TVPlaylist.imported.is_(True),
                TVPlaylist.available.is_(True),
                TVPlaylist.enabled.is_(True),
                TVChannel.enabled_override.is_not(None),
            ]
            if playlist_id:
                exception_conditions.append(TVGroup.playlist_id == playlist_id)
            for theme_id, enabled_count, disabled_count in db.session.execute(
                select(
                    TVGroup.theme_id,
                    func.count(
                        func.distinct(
                            case(
                                (TVChannel.enabled_override.is_(True), TVChannel.preference_key),
                                else_=None,
                            )
                        )
                    ),
                    func.count(
                        func.distinct(
                            case(
                                (TVChannel.enabled_override.is_(False), TVChannel.preference_key),
                                else_=None,
                            )
                        )
                    ),
                )
                .join(TVChannel, TVChannel.group_id == TVGroup.id)
                .join(
                    TVChannelRepresentative,
                    TVChannelRepresentative.channel_id == TVChannel.id,
                )
                .join(TVPlaylist, TVPlaylist.id == TVGroup.playlist_id)
                .where(*exception_conditions)
                .group_by(TVGroup.theme_id)
            ):
                exceptions[int(theme_id)] = (
                    int(enabled_count or 0),
                    int(disabled_count or 0),
                )

        payload = []
        for row in rows:
            enabled_count, disabled_count = exceptions.get(int(row.id), (0, 0))
            source_names = str(row.source_names or "").split(",")
            payload.append(
                {
                    "id": int(row.id),
                    "key": row.key,
                    "name": row.name,
                    "enabled": bool(row.enabled),
                    "channel_policy": row.channel_policy,
                    "has_active_source": bool(row.has_active_source),
                    "channel_count": channel_counts.get(int(row.id), 0),
                    "source_count": int(row.source_count or 0),
                    "source_names": [item for item in source_names if item],
                    "raw_group_count": int(row.group_count or 0),
                    "enabled_exceptions": enabled_count,
                    "disabled_exceptions": disabled_count,
                }
            )
        return {"groups": payload}

    key = _cache_key("groups", playlist_id or 0, active_only, visibility, query.casefold())
    payload, hit = query_cache.get_or_set(key, build_payload, ttl_seconds=120)
    return _json_cache_response(payload, hit)


@bp.get("/api/channels")
@login_required
def channels():
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(12, request.args.get("per_page", 36, type=int)))
    playlist_id = request.args.get("playlist_id", type=int)
    theme_id = request.args.get("theme_id", type=int)
    state = str(request.args.get("state") or "enabled")
    active_only = request.args.get("active_only") == "true"
    favorites_first = request.args.get("favorites_first") == "true"
    sort = str(request.args.get("sort") or "name")
    query = str(request.args.get("q") or "").strip()
    if state not in {"enabled", "disabled", "all", "favorites", "recent"}:
        abort(400, "Unknown channel state.")
    if sort not in {"favorites", "name", "recent"}:
        abort(400, "Unknown channel sort.")

    def build_payload() -> dict:
        effective = _effective_enabled()
        effective_sort = "recent" if state == "recent" else sort
        favorite_order = (
            TVChannelPreference.favorite_position.is_(None),
            TVChannelPreference.favorite_position,
            TVChannel.name,
        )
        conditions = [
            TVPlaylist.imported.is_(True),
            TVPlaylist.available.is_(True),
            TVPlaylist.enabled.is_(True),
            or_(
                TVChannelHealth.status.is_(None),
                TVChannelHealth.status != "offline",
            ),
        ]
        if playlist_id:
            conditions.append(TVChannel.playlist_id == playlist_id)
        if theme_id:
            conditions.append(TVGroup.theme_id == theme_id)
        if active_only:
            conditions.append(TVTheme.enabled.is_(True))
        if query:
            search = f"%{query}%"
            conditions.append(
                or_(
                    TVChannel.name.ilike(search),
                    TVChannel.tvg_name.ilike(search),
                    TVTheme.name.ilike(search),
                    TVGroup.name.ilike(search),
                )
            )
        if state == "enabled":
            conditions.append(effective)
        elif state == "disabled":
            conditions.append(not_(effective))
        elif state == "favorites":
            conditions.append(TVChannelPreference.favorite.is_(True))
        elif state == "recent":
            conditions.append(TVChannelPreference.last_watched_at.is_not(None))

        count_statement = (
            select(func.count(TVChannel.id))
            .join(TVGroup, TVGroup.id == TVChannel.group_id)
            .join(
                TVChannelRepresentative,
                TVChannelRepresentative.channel_id == TVChannel.id,
            )
            .join(TVTheme, TVTheme.id == TVGroup.theme_id)
            .join(TVPlaylist, TVPlaylist.id == TVChannel.playlist_id)
            .outerjoin(
                TVChannelPreference,
                TVChannelPreference.preference_key == TVChannel.preference_key,
            )
            .outerjoin(
                TVChannelHealth,
                TVChannelHealth.preference_key == TVChannel.preference_key,
            )
            .where(*conditions)
        )
        total = int(db.session.scalar(count_statement) or 0)
        statement = (
            select(
                TVChannel,
                TVGroup.name.label("source_group_name"),
                TVTheme.id.label("theme_id"),
                TVTheme.name.label("theme_name"),
                TVTheme.enabled.label("theme_enabled"),
                TVPlaylist.name.label("playlist_name"),
                TVPlaylist.enabled.label("playlist_enabled"),
                effective.label("effective_enabled"),
                func.coalesce(TVChannelPreference.favorite, False).label("favorite"),
                func.coalesce(TVChannelHealth.status, "unknown").label("health_status"),
                TVChannelPreference.last_watched_at.label("last_watched_at"),
                TVTheme.channel_policy.label("theme_channel_policy"),
            )
            .join(TVGroup, TVGroup.id == TVChannel.group_id)
            .join(
                TVChannelRepresentative,
                TVChannelRepresentative.channel_id == TVChannel.id,
            )
            .join(TVTheme, TVTheme.id == TVGroup.theme_id)
            .join(TVPlaylist, TVPlaylist.id == TVChannel.playlist_id)
            .outerjoin(
                TVChannelPreference,
                TVChannelPreference.preference_key == TVChannel.preference_key,
            )
            .outerjoin(
                TVChannelHealth,
                TVChannelHealth.preference_key == TVChannel.preference_key,
            )
            .where(*conditions)
            .order_by(
                *(
                    favorite_order
                    if state == "favorites"
                    else (
                        func.coalesce(TVChannelPreference.favorite, False).desc(),
                    )
                    if favorites_first or effective_sort == "favorites"
                    else (
                        TVChannelPreference.last_watched_at.desc().nullslast(),
                    )
                    if effective_sort == "recent"
                    else (TVTheme.name,)
                ),
                TVChannel.position,
                TVChannel.name,
            )
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        rows = list(db.session.execute(statement))
        favorite_tvg_ids = {
            row[0].tvg_id for row in rows if bool(row.favorite) and row[0].tvg_id
        }
        schedule = now_next_for_ids(favorite_tvg_ids)
        items = []
        for row in rows:
            channel = row[0]
            watched_at = row.last_watched_at
            if watched_at is not None and watched_at.tzinfo is None:
                watched_at = watched_at.replace(tzinfo=timezone.utc)
            items.append(
                {
                    "id": channel.id,
                    "name": channel.name,
                    "logo_url": channel.logo_url,
                    "group_id": channel.group_id,
                    "source_group_name": row.source_group_name,
                    "theme_id": int(row.theme_id),
                    "group_name": row.theme_name,
                    "group_enabled": bool(row.theme_enabled),
                    "playlist_id": channel.playlist_id,
                    "playlist_name": row.playlist_name,
                    "playlist_enabled": bool(row.playlist_enabled),
                    "stream_kind": channel.stream_kind,
                    "tvg_id": channel.tvg_id,
                    "enabled_override": channel.enabled_override,
                    "enabled": bool(row.effective_enabled),
                    "favorite": bool(row.favorite),
                    "health_status": row.health_status,
                    "last_watched_at": watched_at.isoformat() if watched_at else None,
                    "resolved_default": bool(
                        row.theme_channel_policy
                        if row.theme_channel_policy is not None
                        else row.theme_enabled
                    ),
                    "epg": schedule.get(channel.tvg_id) if bool(row.favorite) else None,
                }
            )
        return {
            "channels": items,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": max(1, math.ceil(total / per_page)),
            },
        }

    key = _cache_key(
        "channels",
        page,
        per_page,
        playlist_id or 0,
        theme_id or 0,
        state,
        active_only,
        favorites_first,
        sort,
        query.casefold(),
    )
    payload, hit = query_cache.get_or_set(key, build_payload, ttl_seconds=90)
    return _json_cache_response(payload, hit)


@bp.patch("/api/groups/<int:theme_id>")
@login_required
def update_group(theme_id: int):
    payload = request.get_json(silent=True) or {}
    if type(payload.get("enabled")) is not bool:
        abort(400, "enabled must be a boolean.")
    theme = db.session.get(TVTheme, theme_id)
    if theme is None:
        abort(404)
    previous_enabled = theme.enabled
    theme.enabled = payload["enabled"]
    persist_theme_preference(theme)
    if payload.get("clear_overrides") is True:
        db.session.execute(
            update(TVChannel)
            .where(TVChannel.group_id.in_(select(TVGroup.id).where(TVGroup.theme_id == theme_id)))
            .values(enabled_override=None)
        )
    db.session.commit()
    query_cache.invalidate()
    return jsonify(
        {
            "ok": True,
            "previous_enabled": previous_enabled,
            "affected_channels": theme.channel_count,
        }
    )


@bp.post("/api/groups/<int:theme_id>/channels")
@login_required
def bulk_group_channels(theme_id: int):
    theme = db.session.get(TVTheme, theme_id)
    if theme is None:
        abort(404)
    action = str((request.get_json(silent=True) or {}).get("action") or "")
    values = {"enable": True, "disable": False, "inherit": None}
    if action not in values:
        abort(400, "action must be enable, disable, or inherit.")
    previous_overrides = {
        preference.preference_key: preference.enabled_override
        for preference in db.session.scalars(
            select(TVChannelPreference).where(
                TVChannelPreference.theme_key == theme.key,
                TVChannelPreference.enabled_override.is_not(None),
            )
        )
    }
    for preference_key, enabled_override in db.session.execute(
        select(TVChannel.preference_key, TVChannel.enabled_override)
        .join(TVGroup, TVGroup.id == TVChannel.group_id)
        .where(
            TVGroup.theme_id == theme_id,
            TVChannel.enabled_override.is_not(None),
        )
    ):
        previous_overrides.setdefault(preference_key, enabled_override)
    undo_token = secrets.token_urlsafe(24)
    with _bulk_undo_lock:
        expired = [
            token
            for token, snapshot in _bulk_undo.items()
            if snapshot["expires_at"] <= datetime.now(timezone.utc)
        ]
        for token in expired:
            _bulk_undo.pop(token, None)
        _bulk_undo[undo_token] = {
            "expires_at": datetime.now(timezone.utc) + _BULK_UNDO_TTL,
            "theme_id": theme.id,
            "channel_policy": theme.channel_policy,
            "overrides": previous_overrides,
        }
    theme.channel_policy = values[action]
    persist_theme_preference(theme)
    db.session.execute(
        update(TVChannel)
        .where(TVChannel.group_id.in_(select(TVGroup.id).where(TVGroup.theme_id == theme_id)))
        .values(enabled_override=None)
    )
    db.session.execute(
        update(TVChannelPreference)
        .where(TVChannelPreference.theme_key == theme.key)
        .values(enabled_override=None)
    )
    db.session.commit()
    query_cache.invalidate()
    return jsonify(
        {
            "ok": True,
            "undo_token": undo_token,
            "undo_seconds": int(_BULK_UNDO_TTL.total_seconds()),
            "affected_channels": theme.channel_count,
        }
    )


@bp.post("/api/groups/<int:theme_id>/channels/undo")
@login_required
def undo_bulk_group_channels(theme_id: int):
    token = str((request.get_json(silent=True) or {}).get("token") or "")
    with _bulk_undo_lock:
        snapshot = _bulk_undo.pop(token, None)
    if (
        snapshot is None
        or snapshot["theme_id"] != theme_id
        or snapshot["expires_at"] <= datetime.now(timezone.utc)
    ):
        abort(409, "This undo has expired.")
    theme = db.session.get(TVTheme, theme_id)
    if theme is None:
        abort(404)
    theme.channel_policy = snapshot["channel_policy"]
    persist_theme_preference(theme)
    db.session.execute(
        update(TVChannel)
        .where(TVChannel.group_id.in_(select(TVGroup.id).where(TVGroup.theme_id == theme_id)))
        .values(enabled_override=None)
    )
    db.session.execute(
        update(TVChannelPreference)
        .where(TVChannelPreference.theme_key == theme.key)
        .values(enabled_override=None)
    )
    for preference_key, enabled in snapshot["overrides"].items():
        db.session.execute(
            update(TVChannel)
            .where(TVChannel.preference_key == preference_key)
            .values(enabled_override=enabled)
        )
        db.session.execute(
            update(TVChannelPreference)
            .where(TVChannelPreference.preference_key == preference_key)
            .values(enabled_override=enabled)
        )
        channel = db.session.scalar(
            select(TVChannel)
            .join(TVGroup, TVGroup.id == TVChannel.group_id)
            .where(
                TVChannel.preference_key == preference_key,
                TVGroup.theme_id == theme_id,
            )
            .limit(1)
        )
        if channel is not None:
            _upsert_channel_preference(channel, enabled_override=enabled)
    db.session.commit()
    query_cache.invalidate()
    return jsonify({"ok": True})


@bp.patch("/api/channels/<int:channel_id>")
@login_required
def update_channel(channel_id: int):
    payload = request.get_json(silent=True) or {}
    enabled = payload.get("enabled", "missing")
    if enabled is not None and type(enabled) is not bool:
        abort(400, "enabled must be true, false, or null.")
    channel = db.session.get(TVChannel, channel_id)
    if channel is None:
        abort(404)
    channel.enabled_override = enabled
    _upsert_channel_preference(channel, enabled_override=enabled)
    db.session.commit()
    query_cache.invalidate()
    return jsonify({"ok": True})


@bp.patch("/api/channels/<int:channel_id>/favorite")
@login_required
def update_channel_favorite(channel_id: int):
    payload = request.get_json(silent=True) or {}
    if type(payload.get("favorite")) is not bool:
        abort(400, "favorite must be a boolean.")
    channel = db.session.get(TVChannel, channel_id)
    if channel is None:
        abort(404)
    # A favorite is a promise that the channel is ready from the Watch view.
    # Keep it playable even when its broader bouquet is intentionally off.
    # Without this override, a favorite in (for example) the Arabic bouquet
    # stayed visible but its Play button was disabled.
    enabled_override = True if payload["favorite"] else "unchanged"
    if enabled_override is True:
        channel.enabled_override = True
    _upsert_channel_preference(
        channel,
        favorite=payload["favorite"],
        enabled_override=enabled_override,
    )
    preference = db.session.get(TVChannelPreference, channel.preference_key)
    if preference is not None and not payload["favorite"]:
        preference.favorite_position = None
    db.session.commit()
    query_cache.invalidate()
    if (
        payload["favorite"]
        and channel.tvg_id
        and current_app.config.get("DRAGON_TV_EPG_ENABLED", True)
        and not current_app.config.get("TESTING")
    ):
        epg_coordinator.start(
            current_app._get_current_object(),
            force=True,
            tvg_ids={channel.tvg_id},
        )
    return jsonify({"ok": True, "favorite": payload["favorite"]})


@bp.post("/api/channels/favorites/order")
@login_required
def reorder_favorite_channel():
    """Move one favorite before another and persist the complete favorite order."""
    payload = request.get_json(silent=True) or {}
    channel_id = payload.get("channel_id")
    before_channel_id = payload.get("before_channel_id")
    if type(channel_id) is not int or (
        before_channel_id is not None and type(before_channel_id) is not int
    ):
        abort(400, "channel_id and before_channel_id must be integers or null.")
    if channel_id == before_channel_id:
        return jsonify({"ok": True})

    rows = list(
        db.session.execute(
            select(TVChannel.id, TVChannelPreference)
            .join(
                TVChannelRepresentative,
                TVChannelRepresentative.channel_id == TVChannel.id,
            )
            .join(
                TVChannelPreference,
                TVChannelPreference.preference_key == TVChannel.preference_key,
            )
            .where(TVChannelPreference.favorite.is_(True))
            .order_by(
                TVChannelPreference.favorite_position.is_(None),
                TVChannelPreference.favorite_position,
                TVChannelPreference.name,
                TVChannelPreference.preference_key,
            )
        )
    )
    by_channel_id = {int(row.id): row[1] for row in rows}
    if channel_id not in by_channel_id:
        abort(404, "Favorite channel was not found.")
    if before_channel_id is not None and before_channel_id not in by_channel_id:
        abort(404, "Drop target was not found in favorites.")

    ordered_ids = [int(row.id) for row in rows]
    ordered_ids.remove(channel_id)
    if before_channel_id is None:
        ordered_ids.append(channel_id)
    else:
        ordered_ids.insert(ordered_ids.index(before_channel_id), channel_id)
    for position, ordered_id in enumerate(ordered_ids, start=1):
        by_channel_id[ordered_id].favorite_position = position
    db.session.commit()
    query_cache.invalidate()
    return jsonify({"ok": True, "channel_ids": ordered_ids})


@bp.post("/api/sync")
@login_required
def start_sync():
    payload = request.get_json(silent=True) or {}
    mode = str(payload.get("mode") or "latest")
    if mode not in {"catalog", "fetch", "latest", "selected", "all"}:
        abort(400, "Unknown sync mode.")
    playlist_ids = payload.get("playlist_ids") or []
    if not isinstance(playlist_ids, list) or not all(type(item) is int for item in playlist_ids):
        abort(400, "playlist_ids must be an array of integers.")
    started = sync_coordinator.start(current_app._get_current_object(), mode, playlist_ids)
    if not started:
        return jsonify({"ok": False, "message": "A TV sync is already running."}), 409
    query_cache.invalidate()
    return jsonify({"ok": True, "sync": sync_coordinator.status()}), 202


@bp.get("/api/sync")
@login_required
def sync_status():
    return jsonify(sync_coordinator.status())


@bp.post("/api/health")
@login_required
def start_health_check():
    payload = request.get_json(silent=True) or {}
    theme_id = payload.get("theme_id")
    if theme_id is not None and type(theme_id) is not int:
        abort(400, "theme_id must be an integer or null.")
    if theme_id is not None and db.session.get(TVTheme, theme_id) is None:
        abort(404, "Bouquet was not found.")
    started = health_coordinator.start(current_app._get_current_object(), theme_id=theme_id)
    if not started:
        return jsonify({"ok": False, "message": "A health check is already running."}), 409
    return jsonify({"ok": True, "health": _health_payload()}), 202


@bp.get("/api/health")
@login_required
def health_status():
    return jsonify(_health_payload())


@bp.get("/api/epg")
@login_required
def epg_status():
    return jsonify(epg_status_payload())


@bp.post("/api/epg")
@login_required
def start_epg_refresh():
    started = epg_coordinator.start(current_app._get_current_object(), force=True)
    if not started:
        return jsonify({"ok": False, "message": "A guide refresh is already running."}), 409
    return jsonify({"ok": True, "epg": epg_status_payload()}), 202


def _playback_payload(channel: TVChannel) -> dict:
    candidates = _playback_candidates(channel)
    source_count = len(candidates)
    delivery_kind = candidates[0].stream_kind if candidates else channel.stream_kind
    direct_favorite = bool(
        current_app.config.get("DRAGON_MYTV_DIRECT_FAVORITES")
        and db.session.scalar(
            select(TVChannelPreference.favorite).where(
                TVChannelPreference.preference_key == channel.preference_key
            )
        )
    )
    startup_timeout_seconds = min(
        60, max(20, source_count * STREAM_START_TIMEOUT_SECONDS + 4)
    )
    return {
        "id": channel.id,
        "name": channel.name,
        "logo_url": channel.logo_url,
        # HLS normally uses an authenticated, rewritten manifest. Favorite
        # channels may instead be handed directly to the viewer's device
        # when the host cannot reach their provider.
        "mode": (
            "hls"
            if delivery_kind == "hls"
            else "native"
            if direct_favorite or delivery_kind == "file"
            else "transcode"
        ),
        "url": (
            f"/iptv/direct/{channel.id}"
            if direct_favorite
            else f"/iptv/play/{channel.id}"
        ),
        "delivery": "direct" if direct_favorite else "proxy",
        "source_count": source_count,
        "startup_timeout_seconds": startup_timeout_seconds,
        "capabilities": {
            "live": True,
            "seek": False,
            "quality_selection": False,
            "audio_track_selection": False,
            "subtitle_selection": False,
        },
    }


@bp.get("/api/channels/<int:channel_id>/playback")
@login_required
def playback_info(channel_id: int):
    return jsonify(_playback_payload(_playable_channel(channel_id)))


@bp.post("/api/channels/<int:channel_id>/playback/failover")
@login_required
def playback_failover(channel_id: int):
    """Quarantine a source that failed after HLS startup and pick the next one."""
    channel = _playable_channel(channel_id)
    candidates = _playback_candidates(channel)
    if len(candidates) < 2:
        abort(409, "No alternate source is available for this channel.")
    mark_stream_failure(candidates[0].stream_url)
    query_cache.invalidate()
    return jsonify(_playback_payload(channel))


@bp.get("/direct/<int:channel_id>")
@login_required
def direct(channel_id: int):
    """Redirect an eligible favorite to its provider without proxying media."""
    if not current_app.config.get("DRAGON_MYTV_DIRECT_FAVORITES"):
        abort(404)
    channel = _playable_channel(channel_id)
    favorite = db.session.scalar(
        select(TVChannelPreference.favorite).where(
            TVChannelPreference.preference_key == channel.preference_key
        )
    )
    if not favorite:
        abort(403, "Direct playback is available for favorite channels only.")
    candidates = _playback_candidates(channel)
    if not candidates:
        abort(502, "No direct source is available for this channel.")
    destination = candidates[0].stream_url
    _record_channel_watch(channel, source_url=destination)
    db.session.commit()
    query_cache.invalidate()
    return redirect(destination, code=302)


@bp.get("/play/<int:channel_id>")
@login_required
def play(channel_id: int):
    channel = _playable_channel(channel_id)
    candidates = _playback_candidates(channel)
    last_error_response = None
    source_failed = False
    for attempt, candidate in enumerate(candidates, start=1):
        try:
            response = (
                proxy_file(candidate.stream_url)
                if candidate.stream_kind == "file"
                else proxy_stream(candidate.stream_url, force_manifest=True)
                if candidate.stream_kind == "hls"
                else transcode_stream(candidate.stream_url)
            )
        except (StreamUnavailable, requests.RequestException, OSError):
            mark_stream_failure(candidate.stream_url)
            source_failed = True
            continue
        if response.status_code >= 400:
            last_error_response = response
            if response.status_code != 429:
                mark_stream_failure(candidate.stream_url)
                source_failed = True
            continue
        mark_stream_success(candidate.stream_url)
        record_channel_health(
            channel.preference_key,
            online=True,
            source_url=candidate.stream_url,
        )
        _record_channel_watch(channel, source_url=candidate.stream_url)
        db.session.commit()
        query_cache.invalidate()
        response.headers["X-Dragon-TV-Source-Attempt"] = str(attempt)
        response.headers["X-Dragon-TV-Source-Candidates"] = str(len(candidates))
        return response
    if last_error_response is not None and not source_failed:
        return last_error_response
    record_channel_health(
        channel.preference_key,
        online=False,
        error="No working source passed playback startup.",
    )
    return (
        "No working source is available for this channel. Try again later.",
        502,
    )


@bp.get("/resource/<token>")
@login_required
def hls_resource(token: str):
    try:
        return proxy_stream(read_resource_token(token))
    except (UnsafeStreamUrl, OSError, requests.RequestException) as error:
        return str(error), 502


@bp.get("/transcode/<int:channel_id>")
@login_required
def transcode_live(channel_id: int):
    """Use FFmpeg when a browser cannot tolerate a provider's HLS manifest."""
    channel = _playable_channel(channel_id)
    candidates = _playback_candidates(channel)
    last_error_response = None
    for attempt, candidate in enumerate(candidates, start=1):
        try:
            response = transcode_stream(candidate.stream_url)
        except (StreamUnavailable, requests.RequestException, OSError):
            mark_stream_failure(candidate.stream_url)
            continue
        if response.status_code >= 400:
            last_error_response = response
            if response.status_code != 429:
                mark_stream_failure(candidate.stream_url)
            continue
        mark_stream_success(candidate.stream_url)
        record_channel_health(
            channel.preference_key,
            online=True,
            source_url=candidate.stream_url,
        )
        _record_channel_watch(channel, source_url=candidate.stream_url)
        db.session.commit()
        query_cache.invalidate()
        response.headers["X-Dragon-TV-Source-Attempt"] = str(attempt)
        response.headers["X-Dragon-TV-Source-Candidates"] = str(len(candidates))
        return response
    if last_error_response is not None:
        return last_error_response
    return "No live source could be opened by the local player.", 502


def _playback_candidates(channel: TVChannel) -> list[TVChannel]:
    candidate_rows = list(
        db.session.execute(
            select(TVChannel, TVSource.protected)
            .join(TVPlaylist, TVPlaylist.id == TVChannel.playlist_id)
            .outerjoin(TVSource, TVSource.id == TVPlaylist.source_id)
            .where(
                TVChannel.preference_key == channel.preference_key,
                TVPlaylist.imported.is_(True),
                TVPlaylist.available.is_(True),
            )
            .order_by(TVChannel.id.desc())
            .limit(50)
        )
    )
    # Prefer user-managed and verified sources, but never discard the catalogue
    # copies. Live providers fail after startup often enough that a logical
    # channel needs every distinct source available for late failover.
    unique: dict[str, tuple[TVChannel, bool | None]] = {}
    for item, protected in candidate_rows:
        unique.setdefault(item.stream_url, (item, protected))
    preference = db.session.get(TVChannelPreference, channel.preference_key)
    preferred_fingerprint = (
        preference.preferred_source_fingerprint if preference is not None else ""
    )
    return sorted(
        (item for item, _protected in unique.values()),
        key=lambda item: (
            stream_failure_penalty(item.stream_url),
            0
            if preferred_fingerprint
            and hashlib.sha256(item.stream_url.encode("utf-8", "ignore")).hexdigest()
            == preferred_fingerprint
            else 1,
            0 if unique[item.stream_url][1] is False else 1,
            0 if item.id == channel.id else 1,
            -item.id,
        ),
    )[:PLAYBACK_CANDIDATE_LIMIT]


def _playable_channel(channel_id: int) -> TVChannel:
    effective = _effective_enabled()
    statement = (
        select(TVChannel)
        .join(TVGroup, TVGroup.id == TVChannel.group_id)
        .join(TVTheme, TVTheme.id == TVGroup.theme_id)
        .join(TVPlaylist, TVPlaylist.id == TVChannel.playlist_id)
        .where(
            TVChannel.id == channel_id,
            TVPlaylist.imported.is_(True),
            TVPlaylist.available.is_(True),
            effective,
        )
    )
    channel = db.session.scalar(statement)
    if channel is None:
        abort(404, "Channel is unavailable or disabled.")
    return channel


def _upsert_channel_preference(
    channel: TVChannel,
    *,
    enabled_override: bool | None | str = "unchanged",
    favorite: bool | str = "unchanged",
) -> None:
    theme = channel.group.theme
    values = {
        "preference_key": channel.preference_key,
        "theme_key": theme.key,
        "name": channel.name,
        "tvg_id": channel.tvg_id,
        "logo_url": channel.logo_url,
    }
    insert_values = {
        **values,
        "enabled_override": (None if enabled_override == "unchanged" else enabled_override),
        "favorite": False if favorite == "unchanged" else favorite,
    }
    statement = sqlite_insert(TVChannelPreference).values(insert_values)
    updates = dict(values)
    if enabled_override != "unchanged":
        updates["enabled_override"] = enabled_override
    if favorite != "unchanged":
        updates["favorite"] = favorite
    db.session.execute(
        statement.on_conflict_do_update(
            index_elements=[TVChannelPreference.preference_key], set_=updates
        )
    )
    db.session.execute(
        delete(TVChannelPreference).where(
            TVChannelPreference.preference_key == channel.preference_key,
            TVChannelPreference.favorite.is_(False),
            TVChannelPreference.enabled_override.is_(None),
            TVChannelPreference.last_watched_at.is_(None),
            TVChannelPreference.watch_count == 0,
        )
    )


def _record_channel_watch(channel: TVChannel, *, source_url: str = "") -> None:
    theme = channel.group.theme
    now = datetime.now(timezone.utc)
    statement = sqlite_insert(TVChannelPreference).values(
        preference_key=channel.preference_key,
        theme_key=theme.key,
        name=channel.name,
        tvg_id=channel.tvg_id,
        logo_url=channel.logo_url,
        enabled_override=channel.enabled_override,
        favorite=False,
        last_watched_at=now,
        watch_count=1,
        preferred_source_fingerprint=(
            hashlib.sha256(source_url.encode("utf-8", "ignore")).hexdigest()
            if source_url
            else ""
        ),
    )
    db.session.execute(
        statement.on_conflict_do_update(
            index_elements=[TVChannelPreference.preference_key],
            set_={
                "name": statement.excluded.name,
                "tvg_id": statement.excluded.tvg_id,
                "logo_url": statement.excluded.logo_url,
                "last_watched_at": now,
                "watch_count": TVChannelPreference.watch_count + 1,
                **(
                    {
                        "preferred_source_fingerprint": statement.excluded.preferred_source_fingerprint
                    }
                    if source_url
                    else {}
                ),
            },
        )
    )


@bp.cli.command("sync")
@click.option("--mode", type=click.Choice(["catalog", "fetch", "latest", "all"]), default="latest")
def sync_command(mode: str):
    """Refresh the TV source catalogue and optionally import packages."""
    sync = GithubTVSync()
    ids = sync.discover()
    if mode == "catalog":
        click.echo(f"Catalogued {len(ids)} TV packages")
        return
    selected = (
        list(dict.fromkeys([*sync.changed_ids, *sync.pending_ids]))
        if mode == "fetch"
        else ids
        if mode == "all"
        else ids[-3:]
    )
    for playlist_id in selected:
        result = sync.import_playlist(playlist_id, refresh_representatives=False)
        click.echo(f"Imported {result['channels']:,} channels from package {playlist_id}")
    sync.refresh_representatives()


@bp.cli.command("sync-epg")
@click.option("--force", is_flag=True, help="Refresh even when the cached guide is current.")
def sync_epg_command(force: bool):
    """Refresh Now/Next schedules for favorite TV channels."""
    if not force and not EPGSyncService.is_due():
        click.echo("Favorite channel schedules are already current.")
        return
    result = EPGSyncService().sync()
    click.echo(
        f"Loaded {result['programmes']:,} programme slots for "
        f"{result['matched']:,}/{result['favorites']:,} favorite channels."
    )
