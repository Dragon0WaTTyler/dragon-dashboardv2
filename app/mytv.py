from __future__ import annotations

import secrets

import click
import requests
from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
    session,
)

from .db import get_db
from .services.github_sync import GithubPlaylistSync, sync_coordinator
from .services.streaming import (
    UnsafeStreamUrl,
    proxy_stream,
    read_resource_token,
    transcode_stream,
)


bp = Blueprint("mytv", __name__, url_prefix="/my-tv")


@bp.before_request
def protect_api_writes():
    if request.method in {"POST", "PATCH", "PUT", "DELETE"} and request.path.startswith(
        "/my-tv/api/"
    ):
        expected = session.get("csrf_token")
        received = request.headers.get("X-CSRF-Token")
        if not expected or not received or not secrets.compare_digest(expected, received):
            abort(403, description="Invalid CSRF token")


@bp.get("")
def page():
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return render_template(
        "my_tv.html",
        csrf_token=session["csrf_token"],
        source_repo=f"{current_app.config['MYTV_GITHUB_OWNER']}/{current_app.config['MYTV_GITHUB_REPO']}",
    )


@bp.get("/api/bootstrap")
def bootstrap():
    db = get_db()
    stats = db.execute(
        """
        SELECT
            COUNT(c.id) AS total_channels,
            SUM(CASE WHEN p.enabled = 1 AND COALESCE(c.enabled_override, g.enabled) = 1 THEN 1 ELSE 0 END) AS enabled_channels,
            COUNT(DISTINCT CASE WHEN p.imported = 1 THEN g.id END) AS groups,
            COUNT(DISTINCT CASE WHEN p.imported = 1 THEN p.id END) AS imported_playlists
        FROM playlists p
        LEFT JOIN channel_groups g ON g.playlist_id = p.id
        LEFT JOIN channels c ON c.group_id = g.id
        """
    ).fetchone()
    playlists = [playlist_json(row) for row in db.execute(
        "SELECT * FROM playlists ORDER BY available DESC, discovered_at DESC, id DESC"
    )]
    return jsonify(
        {
            "stats": {
                "total_channels": stats["total_channels"] or 0,
                "enabled_channels": stats["enabled_channels"] or 0,
                "groups": stats["groups"] or 0,
                "imported_playlists": stats["imported_playlists"] or 0,
            },
            "playlists": playlists,
            "sync": sync_coordinator.status(),
        }
    )


@bp.get("/api/groups")
def groups():
    db = get_db()
    playlist_id = request.args.get("playlist_id", type=int)
    query = (request.args.get("q") or "").strip()
    sql = """
        SELECT g.*, p.name AS playlist_name, p.enabled AS playlist_enabled,
               SUM(CASE WHEN c.enabled_override = 1 THEN 1 ELSE 0 END) AS enabled_exceptions,
               SUM(CASE WHEN c.enabled_override = 0 THEN 1 ELSE 0 END) AS disabled_exceptions
        FROM channel_groups g
        JOIN playlists p ON p.id = g.playlist_id
        LEFT JOIN channels c ON c.group_id = g.id
        WHERE p.imported = 1
    """
    params: list = []
    if playlist_id:
        sql += " AND g.playlist_id = ?"
        params.append(playlist_id)
    if query:
        sql += " AND g.name LIKE ?"
        params.append(f"%{query}%")
    sql += " GROUP BY g.id ORDER BY g.name COLLATE NOCASE LIMIT 1000"
    return jsonify({"groups": [group_json(row) for row in db.execute(sql, params)]})


@bp.get("/api/channels")
def channels():
    db = get_db()
    page_number = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(12, request.args.get("per_page", 36, type=int)))
    playlist_id = request.args.get("playlist_id", type=int)
    group_id = request.args.get("group_id", type=int)
    state = request.args.get("state", "enabled")
    query = (request.args.get("q") or "").strip()

    where = ["p.imported = 1", "p.available = 1"]
    params: list = []
    if playlist_id:
        where.append("c.playlist_id = ?")
        params.append(playlist_id)
    if group_id:
        where.append("c.group_id = ?")
        params.append(group_id)
    if query:
        where.append("(c.name LIKE ? OR c.tvg_name LIKE ? OR g.name LIKE ?)")
        params.extend([f"%{query}%"] * 3)
    effective = "(p.enabled = 1 AND COALESCE(c.enabled_override, g.enabled) = 1)"
    if state == "enabled":
        where.append(effective)
    elif state == "disabled":
        where.append(f"NOT {effective}")

    where_sql = " AND ".join(where)
    total = db.execute(
        f"""
        SELECT COUNT(*) AS amount
        FROM channels c
        JOIN channel_groups g ON g.id = c.group_id
        JOIN playlists p ON p.id = c.playlist_id
        WHERE {where_sql}
        """,
        params,
    ).fetchone()["amount"]
    offset = (page_number - 1) * per_page
    rows = db.execute(
        f"""
        SELECT c.*, g.name AS group_name, g.enabled AS group_enabled,
               p.name AS playlist_name, p.enabled AS playlist_enabled,
               {effective} AS effective_enabled
        FROM channels c
        JOIN channel_groups g ON g.id = c.group_id
        JOIN playlists p ON p.id = c.playlist_id
        WHERE {where_sql}
        ORDER BY g.name COLLATE NOCASE, c.position, c.name COLLATE NOCASE
        LIMIT ? OFFSET ?
        """,
        [*params, per_page, offset],
    )
    return jsonify(
        {
            "channels": [channel_json(row) for row in rows],
            "pagination": {
                "page": page_number,
                "per_page": per_page,
                "total": total,
                "pages": max(1, (total + per_page - 1) // per_page),
            },
        }
    )


@bp.patch("/api/playlists/<int:playlist_id>")
def update_playlist(playlist_id: int):
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get("enabled"), bool):
        abort(400, description="enabled must be a boolean")
    db = get_db()
    cursor = db.execute(
        "UPDATE playlists SET enabled = ? WHERE id = ?",
        (int(data["enabled"]), playlist_id),
    )
    db.commit()
    if not cursor.rowcount:
        abort(404)
    return jsonify({"ok": True})


@bp.patch("/api/groups/<int:group_id>")
def update_group(group_id: int):
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get("enabled"), bool):
        abort(400, description="enabled must be a boolean")
    db = get_db()
    cursor = db.execute(
        "UPDATE channel_groups SET enabled = ? WHERE id = ?",
        (int(data["enabled"]), group_id),
    )
    if data.get("clear_overrides") is True:
        db.execute("UPDATE channels SET enabled_override = NULL WHERE group_id = ?", (group_id,))
    db.commit()
    if not cursor.rowcount:
        abort(404)
    return jsonify({"ok": True})


@bp.post("/api/groups/<int:group_id>/channels")
def bulk_group_channels(group_id: int):
    action = (request.get_json(silent=True) or {}).get("action")
    values = {"enable": 1, "disable": 0, "inherit": None}
    if action not in values:
        abort(400, description="action must be enable, disable, or inherit")
    db = get_db()
    exists = db.execute("SELECT 1 FROM channel_groups WHERE id = ?", (group_id,)).fetchone()
    if not exists:
        abort(404)
    db.execute(
        "UPDATE channels SET enabled_override = ? WHERE group_id = ?",
        (values[action], group_id),
    )
    db.commit()
    return jsonify({"ok": True})


@bp.patch("/api/channels/<int:channel_id>")
def update_channel(channel_id: int):
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled", "missing")
    if enabled is not None and type(enabled) is not bool:
        abort(400, description="enabled must be true, false, or null")
    db = get_db()
    cursor = db.execute(
        "UPDATE channels SET enabled_override = ? WHERE id = ?",
        (None if enabled is None else int(enabled), channel_id),
    )
    db.commit()
    if not cursor.rowcount:
        abort(404)
    return jsonify({"ok": True})


@bp.post("/api/sync")
def start_sync():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "latest")
    if mode not in {"catalog", "latest", "selected", "all"}:
        abort(400, description="Unknown sync mode")
    playlist_ids = data.get("playlist_ids") or []
    if not isinstance(playlist_ids, list) or not all(isinstance(item, int) for item in playlist_ids):
        abort(400, description="playlist_ids must be an array of integers")
    started = sync_coordinator.start(current_app._get_current_object(), mode, playlist_ids)
    if not started:
        return jsonify({"ok": False, "message": "A sync is already running"}), 409
    return jsonify({"ok": True, "sync": sync_coordinator.status()}), 202


@bp.get("/api/sync")
def sync_status():
    return jsonify(sync_coordinator.status())


@bp.get("/api/channels/<int:channel_id>/playback")
def playback_info(channel_id: int):
    channel = _playable_channel(channel_id)
    mode = "hls" if channel["stream_kind"] == "hls" else (
        "native" if channel["stream_kind"] == "file" else "transcode"
    )
    return jsonify(
        {
            "id": channel["id"],
            "name": channel["name"],
            "logo_url": channel["logo_url"],
            "mode": mode,
            "url": f"/my-tv/play/{channel['id']}",
        }
    )


@bp.get("/play/<int:channel_id>")
def play(channel_id: int):
    channel = _playable_channel(channel_id)
    try:
        if channel["stream_kind"] == "hls":
            return proxy_stream(channel["stream_url"], force_manifest=True)
        if channel["stream_kind"] == "file":
            return proxy_stream(channel["stream_url"])
        return transcode_stream(channel["stream_url"])
    except (UnsafeStreamUrl, OSError, requests.RequestException) as error:
        return str(error), 502


@bp.get("/resource/<token>")
def hls_resource(token: str):
    try:
        return proxy_stream(read_resource_token(token))
    except (UnsafeStreamUrl, OSError, requests.RequestException) as error:
        return str(error), 502


def _playable_channel(channel_id: int):
    row = get_db().execute(
        """
        SELECT c.*
        FROM channels c
        JOIN channel_groups g ON g.id = c.group_id
        JOIN playlists p ON p.id = c.playlist_id
        WHERE c.id = ?
          AND p.imported = 1
          AND p.available = 1
          AND p.enabled = 1
          AND COALESCE(c.enabled_override, g.enabled) = 1
        """,
        (channel_id,),
    ).fetchone()
    if not row:
        abort(404, description="Channel is unavailable or disabled")
    return row


def playlist_json(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "filename": row["github_path"],
        "size_bytes": row["size_bytes"],
        "enabled": bool(row["enabled"]),
        "imported": bool(row["imported"]),
        "available": bool(row["available"]),
        "channel_count": row["channel_count"],
        "group_count": row["group_count"],
        "sync_status": row["sync_status"],
        "sync_error": row["sync_error"],
        "last_synced_at": row["last_synced_at"],
    }


def group_json(row) -> dict:
    return {
        "id": row["id"],
        "playlist_id": row["playlist_id"],
        "playlist_name": row["playlist_name"],
        "name": row["name"],
        "enabled": bool(row["enabled"]),
        "playlist_enabled": bool(row["playlist_enabled"]),
        "channel_count": row["channel_count"],
        "enabled_exceptions": row["enabled_exceptions"] or 0,
        "disabled_exceptions": row["disabled_exceptions"] or 0,
    }


def channel_json(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "logo_url": row["logo_url"],
        "group_id": row["group_id"],
        "group_name": row["group_name"],
        "group_enabled": bool(row["group_enabled"]),
        "playlist_id": row["playlist_id"],
        "playlist_name": row["playlist_name"],
        "playlist_enabled": bool(row["playlist_enabled"]),
        "stream_kind": row["stream_kind"],
        "enabled_override": (
            None if row["enabled_override"] is None else bool(row["enabled_override"])
        ),
        "enabled": bool(row["effective_enabled"]),
    }


@bp.cli.command("sync")
@click.option("--mode", type=click.Choice(["catalog", "latest", "all"]), default="latest")
def sync_command(mode: str):
    """Refresh the source catalogue and optionally import playlists."""
    syncer = GithubPlaylistSync(current_app.config)
    ids = syncer.discover()
    if mode == "catalog":
        click.echo(f"Catalogued {len(ids)} playlists")
        return
    selected = ids if mode == "all" else ids[-current_app.config["MYTV_IMPORT_LIMIT"] :]
    for playlist_id in selected:
        result = syncer.import_playlist(playlist_id)
        click.echo(f"Imported {result['channels']:,} channels from playlist {playlist_id}")
