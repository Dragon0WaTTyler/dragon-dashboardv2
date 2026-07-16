from __future__ import annotations

import secrets
from string import Template

from flask import Blueprint, Response, abort, current_app, jsonify, render_template, request, session

from .services.notion_media import NotionMediaClient, NotionMediaError
from .services.releases import ReleaseProviderError, build_release_provider
from .services.tmdb import TmdbClient, TmdbError


bp = Blueprint("media", __name__, url_prefix="/media")


@bp.before_request
def protect_api_writes():
    if request.method in {"POST", "PATCH", "PUT", "DELETE"} and request.path.startswith(
        "/media/api/"
    ):
        expected = session.get("csrf_token")
        received = request.headers.get("X-CSRF-Token")
        if not expected or not received or not secrets.compare_digest(expected, received):
            abort(403, description="Invalid CSRF token")


@bp.get("")
def page():
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return render_template(
        "media.html",
        csrf_token=session["csrf_token"],
        player_mode=current_app.config["MEDIA_PLAYER_MODE"],
        webtorrent_cdn_url=current_app.config["WEBTORRENT_CDN_URL"],
    )


@bp.get("/webtorrent-sw.js")
def webtorrent_service_worker():
    source = f'importScripts({current_app.config["WEBTORRENT_SW_CDN_URL"]!r});\n'
    return Response(source, content_type="application/javascript", headers={"Service-Worker-Allowed": "/media/"})


@bp.get("/api/bootstrap")
def bootstrap():
    notion = NotionMediaClient(current_app.config)
    library = []
    notion_status = {"configured": notion.configured, "missing_properties": []}
    error = None
    if notion.configured:
        try:
            library = [_attach_playback(item) for item in notion.list_media()]
            notion_status = notion.configuration()
        except NotionMediaError as exc:
            error = str(exc)
    return jsonify(
        {
            "library": library,
            "notion": notion_status,
            "tmdb_configured": TmdbClient(current_app.config).configured,
            "release_provider_configured": _release_provider_configured(),
            "player_configured": _player_configured(),
            "player_mode": current_app.config["MEDIA_PLAYER_MODE"],
            "error": error,
        }
    )


@bp.get("/api/search")
def search():
    query = (request.args.get("q") or "").strip()
    media_type = (request.args.get("type") or "all").strip().casefold()
    if len(query) < 2:
        return _error("Enter at least two characters", 400)
    if len(query) > 160:
        return _error("Search is limited to 160 characters", 400)
    if media_type not in {"all", "movie", "tv"}:
        return _error("type must be all, movie, or tv", 400)

    notion = NotionMediaClient(current_app.config)
    library = []
    library_error = None
    if notion.configured:
        try:
            needle = query.casefold()
            library = [
                _attach_playback(item)
                for item in notion.list_media()
                if needle in str(item.get("title") or "").casefold()
                and (media_type == "all" or item.get("media_type") == media_type)
            ]
        except NotionMediaError as exc:
            library_error = str(exc)

    tmdb = TmdbClient(current_app.config)
    try:
        discovery = tmdb.search(query, media_type) if tmdb.configured else []
    except TmdbError as exc:
        return _error(str(exc), 502)

    known = {(item.get("media_type"), item.get("tmdb_id")) for item in library}
    for item in discovery:
        item["in_library"] = (item["media_type"], item["tmdb_id"]) in known
    return jsonify({"query": query, "library": library, "discovery": discovery, "library_error": library_error})


@bp.get("/api/tv/<int:tmdb_id>/seasons")
def seasons(tmdb_id: int):
    try:
        return jsonify({"seasons": TmdbClient(current_app.config).seasons(tmdb_id)})
    except TmdbError as exc:
        return _error(str(exc), 502)


@bp.get("/api/tv/<int:tmdb_id>/seasons/<int:season_number>/episodes")
def episodes(tmdb_id: int, season_number: int):
    try:
        return jsonify(
            {"episodes": TmdbClient(current_app.config).episodes(tmdb_id, season_number)}
        )
    except TmdbError as exc:
        return _error(str(exc), 502)


@bp.get("/api/releases")
def releases():
    media_type = (request.args.get("type") or "").casefold()
    tmdb_id = request.args.get("tmdb_id", type=int)
    season = request.args.get("season", type=int)
    episode = request.args.get("episode", type=int)
    if media_type not in {"movie", "tv"} or not tmdb_id:
        return _error("type and tmdb_id are required", 400)
    if media_type == "tv" and episode is not None and season is None:
        return _error("season is required when episode is selected", 400)
    try:
        details, query = TmdbClient(current_app.config).release_query(
            media_type, tmdb_id, season, episode
        )
        results = build_release_provider(current_app.config).search(query, media_type)
    except (TmdbError, ReleaseProviderError) as exc:
        return _error(str(exc), 502)
    return jsonify({"media": details, "release_query": query, "results": results})


@bp.post("/api/library")
def add_to_library():
    data = request.get_json(silent=True) or {}
    media_type = str(data.get("media_type") or "").casefold()
    tmdb_id = _int(data.get("tmdb_id"))
    magnet = str(data.get("magnet_uri") or "").strip()
    if media_type not in {"movie", "tv"} or not tmdb_id:
        return _error("media_type and tmdb_id are required", 400)
    if not magnet.startswith("magnet:?"):
        return _error("A valid magnet URI is required", 400)
    if media_type == "tv" and (_int(data.get("season")) or 0) < 1:
        return _error("A series release requires a season", 400)
    if media_type == "tv" and (_int(data.get("episode")) or 0) < 1:
        return _error("A series release requires an episode", 400)
    if not _player_configured():
        return _error("The selected media player is not configured", 503)
    try:
        details = TmdbClient(current_app.config).details(media_type, tmdb_id)
        saved = NotionMediaClient(current_app.config).upsert(
            {
                "title": details["title"],
                "tmdb_id": details["tmdb_id"],
                "media_type": media_type,
                "year": details.get("year"),
                "poster_url": details.get("poster_url"),
                "overview": details.get("overview"),
                "magnet_uri": magnet,
                "release_title": str(data.get("release_title") or "")[:2000],
                "season": _int(data.get("season")),
                "episode": _int(data.get("episode")),
                "watched": False,
            }
        )
        playback = _playback_payload(magnet)
    except (TmdbError, NotionMediaError) as exc:
        return _error(str(exc), 502)
    created = saved.pop("created", False)
    saved["playback"] = playback
    return jsonify({"item": saved}), 201 if created else 200


@bp.post("/api/library/<page_id>/watched")
def mark_watched(page_id: str):
    data = request.get_json(silent=True) or {}
    watched = data.get("watched", True)
    if not isinstance(watched, bool):
        return _error("watched must be a boolean", 400)
    if not _valid_notion_page_id(page_id):
        return _error("Invalid Notion page ID", 400)
    try:
        item = NotionMediaClient(current_app.config).mark_watched(page_id, watched)
    except NotionMediaError as exc:
        return _error(str(exc), 502)
    return jsonify({"item": item})


def _playback_payload(magnet: str) -> dict:
    mode = current_app.config["MEDIA_PLAYER_MODE"].casefold()
    payload = {"mode": mode, "magnet_uri": magnet}
    if mode == "external":
        template = current_app.config.get("MEDIA_EXTERNAL_PLAYER_URL_TEMPLATE", "")
        if not template:
            raise NotionMediaError("External player URL template is not configured")
        payload["url"] = Template(template).safe_substitute(magnet=magnet)
    return payload


def _attach_playback(item: dict) -> dict:
    result = dict(item)
    if result.get("magnet_uri") and _player_configured():
        result["playback"] = _playback_payload(result["magnet_uri"])
    return result


def _player_configured() -> bool:
    mode = current_app.config["MEDIA_PLAYER_MODE"].casefold()
    if mode == "webtorrent":
        return bool(current_app.config.get("WEBTORRENT_CDN_URL"))
    if mode == "external":
        return bool(current_app.config.get("MEDIA_EXTERNAL_PLAYER_URL_TEMPLATE"))
    return False


def _release_provider_configured() -> bool:
    try:
        return build_release_provider(current_app.config).configured
    except ReleaseProviderError:
        return False


def _error(message: str, status: int):
    return jsonify({"error": message}), status


def _int(value) -> int | None:
    try:
        return int(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None


def _valid_notion_page_id(value: str) -> bool:
    clean = value.replace("-", "")
    return len(clean) == 32 and all(char in "0123456789abcdefABCDEF" for char in clean)
