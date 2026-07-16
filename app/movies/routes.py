from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required

from app.movies.external_library import (
    add_to_library,
    discover_item,
    import_release,
    release_lookup,
    search_catalog,
    sync_notion_library,
    tmdb_catalog_provider,
    writeback_watch,
)
from app.movies.integrations import MediaIntegrationError
from app.movies.repositories import MovieRepository
from app.movies.services import MovieService, movie_detail, movie_item, parse_movie_filters
from app.playback.services import PlaybackService

bp = Blueprint("movies", __name__, url_prefix="/movies")


def _positive_int(value: str | None, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(value or default), maximum))
    except (TypeError, ValueError):
        return default


@bp.get("")
@login_required
def index():
    filters, errors = parse_movie_filters(request.args)
    page = _positive_int(request.args.get("page"), 1, 100000)
    per_page = _positive_int(request.args.get("per_page"), 24, 100)
    offset = (page - 1) * per_page
    library_sync = sync_notion_library()
    movies, total = MovieRepository.list(
        filters,
        limit=per_page,
        offset=offset,
        library_ids=library_sync.library_ids,
    )
    return render_template(
        "movies/index.html",
        active_module="movies",
        movies=[movie_item(movie) for movie in movies],
        filters=filters,
        filter_errors=errors,
        filter_options=MovieRepository.filter_options(library_sync.library_ids),
        page=page,
        per_page=per_page,
        total=total,
        has_previous=page > 1,
        has_next=offset + len(movies) < total,
        library_sync_error=library_sync.error,
    )


@bp.get("/api/search")
@login_required
def api_search():
    query = str(request.args.get("q") or "").strip()
    media_type = str(request.args.get("type") or "all").strip().lower()
    if len(query) < 2:
        return _api_error("Enter at least two characters.")
    if media_type not in {"all", "movie", "tv"}:
        return _api_error("Type must be all, movie, or tv.")
    try:
        results = search_catalog(query[:160], media_type)
    except MediaIntegrationError as exc:
        return _api_error(str(exc), 502)
    return jsonify({"ok": True, **results})


@bp.get("/api/tv/<int:tmdb_id>/seasons")
@login_required
def api_tv_seasons(tmdb_id: int):
    try:
        items = tmdb_catalog_provider().seasons(tmdb_id)
    except MediaIntegrationError as exc:
        return _api_error(str(exc), 502)
    return jsonify({"ok": True, "items": items})


@bp.get("/api/tv/<int:tmdb_id>/seasons/<int:season_number>/episodes")
@login_required
def api_tv_episodes(tmdb_id: int, season_number: int):
    if season_number < 1:
        return _api_error("Choose a valid season.")
    try:
        items = tmdb_catalog_provider().episodes(tmdb_id, season_number)
    except MediaIntegrationError as exc:
        return _api_error(str(exc), 502)
    return jsonify({"ok": True, "items": items})


@bp.get("/api/releases")
@login_required
def api_releases():
    media_type = str(request.args.get("type") or "movie").strip().lower()
    mode = str(request.args.get("mode") or "auto").strip().lower()
    if media_type not in {"movie", "tv"}:
        return _api_error("Type must be movie or tv.")
    if mode not in {"auto", "exact_episode", "season_pack"}:
        return _api_error("Release mode must be auto, exact_episode, or season_pack.")
    try:
        tmdb_id = int(request.args.get("tmdb_id") or 0)
        season = _optional_positive_int(request.args.get("season"))
        episode = _optional_positive_int(request.args.get("episode"))
        if tmdb_id < 1:
            raise ValueError
        if media_type == "tv" and season is None:
            return _api_error("Choose a season first.")
        if media_type == "tv" and mode != "season_pack" and episode is None:
            return _api_error("Choose a season and episode first.")
        lookup = release_lookup(
            media_type=media_type,
            tmdb_id=tmdb_id,
            season=season,
            episode=episode,
            mode=mode,
        )
    except ValueError:
        return _api_error("The TMDB, season, or episode value is invalid.")
    except MediaIntegrationError as exc:
        return _api_error(str(exc), 502)
    return jsonify(
        {
            "ok": True,
            **lookup,
        }
    )


@bp.post("/api/library")
@login_required
def api_library():
    payload = request.get_json(silent=True) or {}
    media_type = str(payload.get("media_type") or "").strip().lower()
    if media_type not in {"movie", "tv"}:
        return _api_error("Type must be movie or tv.")
    try:
        movie = add_to_library(
            media_type=media_type,
            tmdb_id=int(payload.get("tmdb_id") or 0),
            season=_optional_positive_int(payload.get("season")),
        )
    except (TypeError, ValueError) as exc:
        return _api_error(str(exc) or "The selected title is invalid.")
    except MediaIntegrationError as exc:
        return _api_error(str(exc), 502)
    return jsonify(
        {
            "ok": True,
            "movie_id": movie.id,
            "detail_url": url_for("movies.detail", movie_id=movie.id),
        }
    )


@bp.post("/api/import")
@login_required
def api_import():
    payload = request.get_json(silent=True) or {}
    media_type = str(payload.get("media_type") or "").strip().lower()
    magnet_uri = str(payload.get("magnet_uri") or "").strip()
    if media_type not in {"movie", "tv"}:
        return _api_error("Type must be movie or tv.")
    if not magnet_uri.startswith("magnet:?") or len(magnet_uri) > 12000:
        return _api_error("Choose a valid magnet release.")
    try:
        movie = import_release(
            media_type=media_type,
            tmdb_id=int(payload.get("tmdb_id") or 0),
            magnet_uri=magnet_uri,
            release_title=str(payload.get("release_title") or "")[:500],
            tracker=str(payload.get("tracker") or "Unknown tracker")[:160],
            seeders=max(0, int(payload.get("seeders") or 0)),
            size=max(0, int(payload.get("size") or 0)),
            season=_optional_positive_int(payload.get("season")),
            episode=_optional_positive_int(payload.get("episode")),
            release_mode=str(payload.get("release_mode") or "episode").strip().lower(),
        )
    except (TypeError, ValueError) as exc:
        return _api_error(str(exc) or "The selected release is invalid.")
    except MediaIntegrationError as exc:
        return _api_error(str(exc), 502)
    return jsonify(
        {
            "ok": True,
            "movie_id": movie.id,
            "detail_url": url_for("movies.detail", movie_id=movie.id),
        }
    )


@bp.post("/<movie_id>/watch")
@login_required
def api_watch(movie_id: str):
    movie = MovieRepository.get(movie_id)
    if movie is None:
        abort(404)
    try:
        writeback_watch(movie, started=True)
    except MediaIntegrationError as exc:
        return _api_error(str(exc), 502)
    return jsonify({"ok": True})


@bp.get("/<movie_id>")
@login_required
def detail(movie_id: str):
    movie = MovieRepository.get(movie_id)
    if movie is None:
        abort(404)
    local_player_enabled = (
        current_app.config["DRAGON_PLAYBACK_ENABLED"]
        and current_app.config["DRAGON_MAGNETS_ENABLED"]
    )
    subtitles_enabled = (
        local_player_enabled
        and current_app.config["DRAGON_SUBTITLES_ENABLED"]
        and bool(current_app.config["DRAGON_SUBDL_API_KEY"])
    )
    return render_template(
        "movies/detail.html",
        active_module="movies",
        movie=movie_detail(movie),
        vidsrc_enabled=(
            current_app.config["DRAGON_PLAYBACK_ENABLED"]
            and current_app.config["DRAGON_VIDSRC_ENABLED"]
        ),
        local_player_enabled=local_player_enabled,
        subtitles_enabled=subtitles_enabled,
        player_sources=PlaybackService.player_sources(movie_id) if local_player_enabled else [],
    )


@bp.get("/discover/<media_type>/<int:tmdb_id>")
@login_required
def discover(media_type: str, tmdb_id: int):
    media_type = media_type.strip().lower()
    if media_type not in {"movie", "tv"}:
        abort(404)
    try:
        item = discover_item(media_type, tmdb_id)
    except MediaIntegrationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("movies.index"))
    if item["in_library"] and item["local_id"]:
        return redirect(url_for("movies.detail", movie_id=item["local_id"]))
    return render_template(
        "movies/discover.html",
        active_module="movies",
        media=item,
    )


@bp.post("/<movie_id>/status")
@login_required
def update_status(movie_id: str):
    movie = MovieRepository.get(movie_id)
    if movie is None:
        abort(404)
    try:
        MovieService.set_status(movie, str(request.form.get("status") or ""))
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        if movie.status in {"finished", "watched"}:
            try:
                writeback_watch(movie, started=False)
            except MediaIntegrationError as exc:
                flash(f"Status saved locally, but Notion could not update: {exc}", "error")
            else:
                flash("Movie status and Notion were updated.", "success")
        else:
            flash("Movie status updated.", "success")
    return redirect(url_for("movies.detail", movie_id=movie_id))


@bp.post("/<movie_id>/score")
@login_required
def update_score(movie_id: str):
    movie = MovieRepository.get(movie_id)
    if movie is None:
        abort(404)
    raw_score = str(request.form.get("score") or "").strip()
    try:
        score = float(raw_score) if raw_score else None
        MovieService.set_score(movie, score)
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Personal score updated.", "success")
    return redirect(url_for("movies.detail", movie_id=movie_id))


def _optional_positive_int(value) -> int | None:
    if value in {None, ""}:
        return None
    parsed = int(value)
    if parsed < 1:
        raise ValueError
    return parsed


def _api_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": {"message": message}}), status
