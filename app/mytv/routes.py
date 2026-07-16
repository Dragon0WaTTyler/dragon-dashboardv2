from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import click
import requests
from flask import Blueprint, abort, current_app, jsonify, render_template, request
from flask_login import login_required
from sqlalchemy import case, func, not_, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.extensions import db
from app.mytv.cache import query_cache
from app.mytv.health import health_coordinator, record_channel_health
from app.mytv.models import (
    TVChannel,
    TVChannelHealth,
    TVChannelPreference,
    TVChannelRepresentative,
    TVGroup,
    TVPlaylist,
    TVTheme,
)
from app.mytv.services import (
    SOURCE_OWNER,
    SOURCE_REPOSITORY,
    GithubTVSync,
    sync_coordinator,
)
from app.services.streaming import UnsafeStreamUrl, proxy_stream, read_resource_token
from app.mytv.streaming import (
    StreamUnavailable,
    mark_stream_failure,
    mark_stream_success,
    proxy_file,
    stream_failure_penalty,
    transcode_stream,
)

bp = Blueprint("mytv", __name__, url_prefix="/my-tv")
PLAYBACK_CANDIDATE_LIMIT = 3


def _effective_enabled():
    return func.coalesce(
        TVChannel.enabled_override, TVTheme.channel_policy, TVTheme.enabled
    ).is_(True)


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
            select(TVChannelHealth.status, func.count(TVChannelHealth.preference_key))
            .group_by(TVChannelHealth.status)
        )
    }
    latest = db.session.scalar(select(func.max(TVChannelHealth.checked_at)))
    if latest is not None and latest.tzinfo is None:
        latest = latest.replace(tzinfo=UTC)
    checked = counts.get("online", 0) + counts.get("offline", 0)
    return {
        **health_coordinator.status(),
        "checked": checked,
        "known_online": counts.get("online", 0),
        "known_offline": counts.get("offline", 0),
        "needs_check": checked == 0
        or latest is None
        or latest < datetime.now(UTC) - timedelta(hours=10),
    }


@bp.get("")
@login_required
def index():
    return render_template(
        "mytv/index.html",
        active_module="mytv",
        source_repo=f"{SOURCE_OWNER}/{SOURCE_REPOSITORY}",
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
                    TVChannelHealth.preference_key
                    == TVChannelRepresentative.preference_key,
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
                select(func.count(TVPlaylist.id)).where(TVPlaylist.imported.is_(True))
            )
            or 0
        )
        repo_files = int(
            db.session.scalar(
                select(func.count(TVPlaylist.id)).where(
                    TVPlaylist.available.is_(True)
                )
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
        return {
            "stats": {
                "total_channels": total_channels,
                "enabled_channels": enabled_channels,
                "groups": theme_count,
                "imported_playlists": imported_sources,
                "repo_files": repo_files,
                "pending_files": pending_files,
            },
        }

    cached, hit = query_cache.get_or_set(
        _cache_key("bootstrap"), build_payload, ttl_seconds=60
    )
    return _json_cache_response(
        {
            **cached,
            "sync": sync_coordinator.status(),
            "health": _health_payload(),
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
            conditions.append(
                or_(TVTheme.name.ilike(search), TVGroup.name.ilike(search))
            )

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
            .order_by(TVTheme.name)
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

    key = _cache_key(
        "groups", playlist_id or 0, active_only, visibility, query.casefold()
    )
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
    query = str(request.args.get("q") or "").strip()
    if state not in {"enabled", "disabled", "all", "favorites"}:
        abort(400, "Unknown channel state.")

    def build_payload() -> dict:
        effective = _effective_enabled()
        conditions = [
            TVPlaylist.imported.is_(True),
            TVPlaylist.available.is_(True),
            or_(
                TVChannelHealth.status.is_(None),
                TVChannelHealth.status != "offline",
            ),
        ]
        if playlist_id:
            conditions.append(TVChannel.playlist_id == playlist_id)
        if theme_id:
            conditions.append(TVGroup.theme_id == theme_id)
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
                func.coalesce(TVChannelHealth.status, "unknown").label(
                    "health_status"
                ),
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
            .order_by(TVTheme.name, TVChannel.position, TVChannel.name)
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        items = []
        for row in db.session.execute(statement):
            channel = row[0]
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
                    "enabled_override": channel.enabled_override,
                    "enabled": bool(row.effective_enabled),
                    "favorite": bool(row.favorite),
                    "health_status": row.health_status,
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
    theme.enabled = payload["enabled"]
    if payload.get("clear_overrides") is True:
        db.session.execute(
            update(TVChannel)
            .where(
                TVChannel.group_id.in_(
                    select(TVGroup.id).where(TVGroup.theme_id == theme_id)
                )
            )
            .values(enabled_override=None)
        )
    db.session.commit()
    query_cache.invalidate()
    return jsonify({"ok": True})


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
    theme.channel_policy = values[action]
    db.session.execute(
        update(TVChannel)
        .where(
            TVChannel.group_id.in_(
                select(TVGroup.id).where(TVGroup.theme_id == theme_id)
            )
        )
        .values(enabled_override=None)
    )
    db.session.execute(
        update(TVChannelPreference)
        .where(TVChannelPreference.theme_key == theme.key)
        .values(enabled_override=None)
    )
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
    _upsert_channel_preference(channel, favorite=payload["favorite"])
    db.session.commit()
    query_cache.invalidate()
    return jsonify({"ok": True, "favorite": payload["favorite"]})


@bp.post("/api/sync")
@login_required
def start_sync():
    payload = request.get_json(silent=True) or {}
    mode = str(payload.get("mode") or "latest")
    if mode not in {"catalog", "fetch", "latest", "selected", "all"}:
        abort(400, "Unknown sync mode.")
    playlist_ids = payload.get("playlist_ids") or []
    if not isinstance(playlist_ids, list) or not all(
        type(item) is int for item in playlist_ids
    ):
        abort(400, "playlist_ids must be an array of integers.")
    started = sync_coordinator.start(
        current_app._get_current_object(), mode, playlist_ids
    )
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
    started = health_coordinator.start(
        current_app._get_current_object(), theme_id=theme_id
    )
    if not started:
        return jsonify({"ok": False, "message": "A health check is already running."}), 409
    return jsonify({"ok": True, "health": _health_payload()}), 202


@bp.get("/api/health")
@login_required
def health_status():
    return jsonify(_health_payload())


@bp.get("/api/channels/<int:channel_id>/playback")
@login_required
def playback_info(channel_id: int):
    channel = _playable_channel(channel_id)
    return jsonify(
        {
            "id": channel.id,
            "name": channel.name,
            "logo_url": channel.logo_url,
            "mode": "native" if channel.stream_kind == "file" else "transcode",
            "url": f"/my-tv/play/{channel.id}",
        }
    )


@bp.get("/play/<int:channel_id>")
@login_required
def play(channel_id: int):
    channel = _playable_channel(channel_id)
    candidates = _playback_candidates(channel)
    for attempt, candidate in enumerate(candidates, start=1):
        try:
            response = (
                proxy_file(candidate.stream_url)
                if candidate.stream_kind == "file"
                else transcode_stream(candidate.stream_url)
            )
        except (StreamUnavailable, requests.RequestException, OSError):
            mark_stream_failure(candidate.stream_url)
            continue
        if response.status_code >= 400:
            return response
        mark_stream_success(candidate.stream_url)
        record_channel_health(
            channel.preference_key,
            online=True,
            source_url=candidate.stream_url,
        )
        response.headers["X-Dragon-TV-Source-Attempt"] = str(attempt)
        response.headers["X-Dragon-TV-Source-Candidates"] = str(len(candidates))
        return response
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
def hls_resource(token: str):
    try:
        return proxy_stream(read_resource_token(token))
    except (UnsafeStreamUrl, OSError, requests.RequestException) as error:
        return str(error), 502


def _playback_candidates(channel: TVChannel) -> list[TVChannel]:
    rows = list(
        db.session.scalars(
            select(TVChannel)
            .join(TVPlaylist, TVPlaylist.id == TVChannel.playlist_id)
            .where(
                TVChannel.preference_key == channel.preference_key,
                TVPlaylist.imported.is_(True),
                TVPlaylist.available.is_(True),
            )
            .order_by(TVChannel.id.desc())
            .limit(50)
        )
    )
    unique: dict[str, TVChannel] = {}
    for item in rows:
        unique.setdefault(item.stream_url, item)
    return sorted(
        unique.values(),
        key=lambda item: (
            stream_failure_penalty(item.stream_url),
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
        "enabled_override": (
            None if enabled_override == "unchanged" else enabled_override
        ),
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


@bp.cli.command("sync")
@click.option(
    "--mode", type=click.Choice(["catalog", "fetch", "latest", "all"]), default="latest"
)
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
        click.echo(
            f"Imported {result['channels']:,} channels from package {playlist_id}"
        )
    sync.refresh_representatives()
