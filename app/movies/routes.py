from __future__ import annotations

import json

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required

from app.movies.browse import browse_catalog, parse_browse_query
from app.movies.collections import (
    active_movie_collections,
    collection_catalog,
    movie_collection,
)
from app.movies.external_library import (
    add_to_library,
    discover_item,
    import_release,
    notion_movie_provider,
    refresh_movie_metadata,
    release_lookup,
    resolve_missing_tmdb_identity,
    search_catalog,
    sync_notion_library,
    tmdb_catalog_provider,
    writeback_watch,
)
from app.movies.integrations import MediaIntegrationError
from app.movies.models import Movie
from app.movies.rails import discovery_rails, provider_context
from app.movies.repositories import MovieRepository
from app.movies.scoring import notion_score_options, score_option_for_input
from app.movies.services import (
    MovieService,
    movie_detail,
    movie_item,
    parse_movie_filters,
    tv_season_workspace,
    tv_show_workspace,
)
from app.movies.snapshots import (
    MoviesSnapshotConflictError,
    MoviesSnapshotValidationError,
    apply_movies_snapshot,
    export_movies_snapshot,
    movies_snapshot_digest,
    preview_movies_snapshot,
)
from app.playback.identity import PlaybackIdentity
from app.playback.providers import (
    ID_CATALOG_EMBED_PROVIDER_SPECS,
    build_provider_registry_from_config,
)
from app.playback.services import PlaybackService

bp = Blueprint("movies", __name__, url_prefix="/movies")

# Snapshot restore is intentionally a bounded, authenticated operation.  The
# payload contains canonical personal memory only; large catalog or runtime exports do
# not belong on this endpoint.
_MAX_MOVIES_SNAPSHOT_BYTES = 5 * 1024 * 1024


def _movie_preferences() -> dict:
    from app.admin.control_center import preference_store

    return dict(preference_store().read()["sections"]["movies"]["movie_preferences"])


@bp.context_processor
def movie_template_preferences() -> dict:
    """Provide the compact Movies display defaults to every Movies template."""
    return {"movie_preferences": _movie_preferences()}


def _playback_is_enabled() -> bool:
    """Return the single server-side gate for every playable surface."""
    return bool(current_app.config["DRAGON_PLAYBACK_ENABLED"])


def _enabled_indexed_embed_providers() -> frozenset[str]:
    if not _playback_is_enabled():
        return frozenset()
    registry = build_provider_registry_from_config(current_app.config)
    direct_provider_keys = {spec.key for spec in ID_CATALOG_EMBED_PROVIDER_SPECS}
    return PlaybackService.enabled_provider_keys(
        registry.keys() - {"vidsrc"} - direct_provider_keys
    )


def _enabled_id_catalog_embed_providers() -> frozenset[str]:
    if not _playback_is_enabled():
        return frozenset()
    registry = build_provider_registry_from_config(current_app.config)
    provider_keys = {spec.key for spec in ID_CATALOG_EMBED_PROVIDER_SPECS}
    return PlaybackService.enabled_provider_keys(registry.keys() & provider_keys)


def _provider_priorities() -> dict[str, int]:
    registry = build_provider_registry_from_config(current_app.config)
    return {
        key: int(preference["priority"])
        for key, preference in PlaybackService.provider_preferences(registry.keys()).items()
    }


def _indexed_provider_options() -> list[dict[str, str]]:
    registry = build_provider_registry_from_config(current_app.config)
    direct_provider_keys = {spec.key for spec in ID_CATALOG_EMBED_PROVIDER_SPECS}
    enabled_keys = PlaybackService.enabled_provider_keys(
        registry.keys() - {"vidsrc"} - direct_provider_keys
    )
    return [
        {"key": key, "label": registry.require(key).display_name} for key in sorted(enabled_keys)
    ]


def _vidsrc_is_usable_candidate(movie: Movie) -> bool:
    external_ids = dict(movie.external_ids or {})
    return bool(
        _playback_is_enabled()
        and current_app.config["DRAGON_VIDSRC_ENABLED"]
        and "vidsrc" in PlaybackService.enabled_provider_keys({"vidsrc"})
        and (external_ids.get("imdb_id") or external_ids.get("tmdb_id"))
    )


def _id_catalog_embed_candidates(movie: Movie) -> list[dict]:
    external_ids = dict(movie.external_ids or {})
    if not external_ids.get("tmdb_id"):
        return []
    registry = build_provider_registry_from_config(current_app.config)
    priorities = _provider_priorities()
    candidates = []
    for key in _enabled_id_catalog_embed_providers():
        candidates.append(
            {
                "id": f"provider-{key}",
                "provider": key,
                "label": registry.require(key).display_name,
                "quality": "",
                "priority": priorities.get(key, 100),
                "id_catalog": True,
                "enabled": True,
                "source_type_label": "Configured embed provider",
                "availability_status": "UNKNOWN",
                "availability_checked": False,
                "availability_fresh": False,
            }
        )
    return candidates


def _discover_embed_player_sources(media: dict) -> list[dict]:
    """Build safe, non-persistent player choices for a TMDB-only preview.

    Discovery pages do not have a local ``Movie.id`` yet, so they cannot use
    the library-backed source selector.  Only providers that resolve directly
    from a TMDB identity are eligible here; indexed providers still require a
    Dragon-owned per-title mapping and remain available after library import.
    """
    if not _playback_is_enabled():
        return []
    tmdb_id = str(media.get("tmdb_id") or "").strip()
    media_type = str(media.get("media_type") or "").strip().lower()
    if not tmdb_id.isdigit() or media_type not in {"movie", "tv"}:
        return []

    registry = build_provider_registry_from_config(current_app.config)
    enabled = PlaybackService.enabled_provider_keys(registry.keys())
    priorities = _provider_priorities()
    sources: list[dict] = []
    if current_app.config.get("DRAGON_VIDSRC_ENABLED") and "vidsrc" in enabled:
        sources.append(
            {
                "id": "preview-vidsrc",
                "provider": "vidsrc",
                "label": "VidSrc",
                "priority": priorities.get("vidsrc", 100),
            }
        )
    for spec in ID_CATALOG_EMBED_PROVIDER_SPECS:
        if spec.key not in enabled:
            continue
        provider = registry.get(spec.key)
        if provider is None:
            continue
        sources.append(
            {
                "id": f"preview-{spec.key}",
                "provider": spec.key,
                "label": provider.display_name,
                "priority": priorities.get(spec.key, spec.default_priority),
            }
        )
    return sorted(sources, key=lambda source: (source["priority"], source["label"].casefold()))


def _jackett_is_eligible(
    movie: Movie,
    *,
    indexed_embed_sources: list[dict],
    player_sources: list[dict],
) -> bool:
    return bool(
        not _vidsrc_is_usable_candidate(movie)
        and not _id_catalog_embed_candidates(movie)
        and not indexed_embed_sources
        and not player_sources
    )


def _jackett_search_available(movie: Movie) -> bool:
    """A person can compare Jackett releases whenever the title has a TMDb identity."""
    return bool((movie.external_ids or {}).get("tmdb_id"))


def _embed_player_sources(movie: Movie, indexed_embed_sources: list[dict]) -> list[dict]:
    if not _playback_is_enabled():
        return []
    priorities = _provider_priorities()
    sources: list[dict] = []
    if _vidsrc_is_usable_candidate(movie):
        sources.append(
            {
                "id": "vidsrc",
                "provider": "vidsrc",
                "label": "VidSrc",
                "quality": "",
                "priority": priorities.get("vidsrc", 100),
                "enabled": True,
                "source_type_label": "Configured embed provider",
                "availability_status": "UNKNOWN",
                "availability_checked": False,
                "availability_fresh": False,
            }
        )
    sources.extend(_id_catalog_embed_candidates(movie))
    sources.extend(
        {
            **dict(item),
            "priority": int(item.get("priority") or priorities.get(item["provider"], 100)),
        }
        for item in indexed_embed_sources
    )
    return sorted(
        sources,
        key=lambda source: priorities.get(source["provider"], 100),
    )


def _default_player_selection(
    last_selected_source, player_sources: list[dict]
) -> tuple[str, str]:
    """Prefer the saved local fallback when no source exists in the exact scope."""
    if last_selected_source is not None:
        return last_selected_source.id, last_selected_source.provider
    selected_local = next((source for source in player_sources if source.get("selected")), None)
    if selected_local is not None:
        return str(selected_local["id"]), "local"
    return "", ""


def _positive_int(value: str | None, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(value or default), maximum))
    except (TypeError, ValueError):
        return default


def _movie_score_options() -> list:
    labels = []
    provider = notion_movie_provider()
    if provider and provider.configured:
        loader = getattr(provider, "movie_score_option_labels", None)
        if callable(loader):
            try:
                labels = loader()
            except MediaIntegrationError:
                labels = []
    return notion_score_options(labels or None)


def _snapshot_request() -> tuple[dict, str]:
    content_length = request.content_length
    if content_length is not None and content_length > _MAX_MOVIES_SNAPSHOT_BYTES:
        raise MoviesSnapshotValidationError("Movies snapshots must be 5 MiB or smaller.")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise MoviesSnapshotValidationError("Send a JSON Movies snapshot object.")
    snapshot = payload.get("snapshot", payload)
    if not isinstance(snapshot, dict):
        raise MoviesSnapshotValidationError("snapshot must be an object.")
    return snapshot, str(payload.get("preview_digest") or "")


@bp.get("")
@login_required
def index():
    library_context = _library_context()
    filters = library_context["filters"]
    preferences = library_context["preferences"]
    continue_items = [
        movie_item(movie)
        for movie in MovieRepository.continue_watching(library_ids=library_context["library_ids"])
    ]
    want_to_watch = [
        movie_item(movie)
        for movie in MovieRepository.watch_next(
            limit=12, library_ids=library_context["library_ids"]
        )
    ]
    personal_pick = MovieService.what_should_i_watch()
    availability_region = str(
        request.args.get("region") or preferences.get("preferred_region") or "US"
    ).upper()
    if len(availability_region) != 2 or not availability_region.isalpha():
        availability_region = "US"
    selected_provider_id = request.args.get("provider", type=int)
    availability = provider_context(
        region=availability_region,
        selected_provider_id=selected_provider_id,
    )
    because_you_watched = MovieService.because_you_watched(
        anchor_id=request.args.get("because")
    )
    recommendations = MovieService.recommendation_pool(
        category=filters["category"], source=filters["source"]
    )["items"]
    recommendation = recommendations[0] if recommendations else None
    home_focus = continue_items[0] if continue_items else personal_pick or recommendation
    home_focus_kind = (
        "resume" if continue_items else "personal" if personal_pick else "recommendation"
    )
    hero_candidates: list[dict] = []
    seen_hero_ids: set[str] = set()
    for candidate in [*continue_items, *want_to_watch, personal_pick, *recommendations]:
        if not candidate or not candidate.get("id"):
            continue
        candidate_id = str(candidate["id"])
        if candidate_id in seen_hero_ids:
            continue
        seen_hero_ids.add(candidate_id)
        hero_candidates.append(
            {
                key: candidate.get(key)
                for key in (
                    "id",
                    "title",
                    "media_type",
                    "year",
                    "runtime_minutes",
                    "personal_score",
                    "genre_names",
                    "overview",
                    "progress",
                    "status",
                    "is_favorite",
                    "poster_url",
                    "backdrop_url",
                    "eligibility_reason",
                )
            }
        )
        if len(hero_candidates) >= 8:
            break
    return render_template(
        "movies/index.html",
        active_module="movies",
        **library_context,
        continue_watching=continue_items,
        want_to_watch=want_to_watch,
        home_focus=home_focus,
        home_focus_kind=home_focus_kind,
        hero_candidates=hero_candidates,
        personal_pick=personal_pick,
        because_you_watched=because_you_watched,
        because_anchor_id=request.args.get("because", type=int),
        availability=availability,
        discovery_rails=discovery_rails(),
        recommendation=recommendation,
        recommendations=recommendations,
        movie_preferences=preferences,
    )


def _library_context() -> dict:
    """Build the shared, URL-driven Library page state for Home and /library."""
    filters, errors = parse_movie_filters(request.args)
    from app.admin.control_center import preference_store

    section_preferences = preference_store().read()["sections"]["movies"]
    preferences = dict(section_preferences["movie_preferences"])
    if "status" not in request.args:
        default_status = {
            "watching": "watching",
            "library": "",
            "finished": "finished",
            "wishlist": "want_to_watch",
        }.get(section_preferences["default_view"], "")
        filters["status"] = default_status
    if "sort" not in request.args:
        filters["sort"] = {
            "recent": "recently_updated",
            "last_watched": "recently_updated",
            "rating": "score_desc",
            "year": "year_desc",
            "title": "title_asc",
        }.get(section_preferences["default_sort"], "recently_updated")
    if section_preferences["hide_completed"] and not filters["status"]:
        filters["hide_completed"] = True
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
    return {
        "movies": [movie_item(movie) for movie in movies],
        "filters": filters,
        "filter_errors": errors,
        "filter_options": MovieRepository.filter_options(library_sync.library_ids),
        "page": page,
        "per_page": per_page,
        "total": total,
        "has_previous": page > 1,
        "has_next": offset + len(movies) < total,
        "library_sync_error": library_sync.error,
        "preferences": preferences,
        "library_ids": library_sync.library_ids,
    }


@bp.get("/library")
@login_required
def library():
    context = _library_context()
    return render_template(
        "movies/library.html",
        active_module="movies",
        **context,
        movie_preferences=context["preferences"],
    )


@bp.get("/watch-next")
@login_required
def watch_next():
    library_sync = sync_notion_library()
    movies = MovieRepository.watch_next(limit=100, library_ids=library_sync.library_ids)
    return render_template(
        "movies/watch_next.html",
        active_module="movies",
        movies=[movie_item(movie) for movie in movies],
        library_sync_error=library_sync.error,
    )


@bp.get("/snapshot/export")
@login_required
def export_snapshot():
    snapshot = export_movies_snapshot(owner_user_id=current_user.id)
    return Response(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=dragon-movies-snapshot-v1.json"},
    )


@bp.post("/snapshot/import/preview")
@login_required
def preview_snapshot_import():
    try:
        snapshot, _ = _snapshot_request()
        preview = preview_movies_snapshot(snapshot, owner_user_id=current_user.id)
    except MoviesSnapshotValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    session["movies_snapshot_preview_digest"] = preview["digest"]
    return jsonify({"preview": preview})


@bp.post("/snapshot/import/apply")
@login_required
def apply_snapshot_import():
    try:
        snapshot, preview_digest = _snapshot_request()
        digest = movies_snapshot_digest(snapshot)
    except MoviesSnapshotValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    if not preview_digest or preview_digest != session.get("movies_snapshot_preview_digest"):
        return jsonify({"error": "Preview this exact Movies snapshot before applying it."}), 409
    if digest != preview_digest:
        return jsonify({"error": "The snapshot changed after preview; preview it again."}), 409
    try:
        result = apply_movies_snapshot(snapshot, owner_user_id=current_user.id)
    except (MoviesSnapshotValidationError, MoviesSnapshotConflictError) as exc:
        return jsonify({"error": str(exc)}), 400
    session.pop("movies_snapshot_preview_digest", None)
    return jsonify({"result": result})


@bp.get("/lists")
@login_required
def custom_lists():
    return render_template(
        "movies/custom_lists.html",
        active_module="movies",
        custom_lists=MovieService.custom_lists(current_user.id),
    )


@bp.post("/lists")
@login_required
def create_custom_list():
    try:
        MovieService.create_custom_list(
            current_user.id,
            title=str(request.form.get("title") or ""),
            description=str(request.form.get("description") or ""),
        )
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Custom list created.", "success")
    return redirect(url_for("movies.custom_lists"))


@bp.post("/lists/<custom_list_id>")
@login_required
def update_custom_list(custom_list_id: str):
    custom_list = MovieService.custom_list_for_owner(current_user.id, custom_list_id)
    if custom_list is None:
        abort(404)
    try:
        MovieService.update_custom_list(
            custom_list,
            title=str(request.form.get("title") or ""),
            description=str(request.form.get("description") or ""),
        )
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Custom list updated.", "success")
    return redirect(url_for("movies.custom_lists"))


@bp.post("/lists/<custom_list_id>/delete")
@login_required
def delete_custom_list(custom_list_id: str):
    custom_list = MovieService.custom_list_for_owner(current_user.id, custom_list_id)
    if custom_list is None:
        abort(404)
    MovieService.delete_custom_list(custom_list)
    flash("Custom list deleted.", "success")
    return redirect(url_for("movies.custom_lists"))


@bp.post("/lists/<custom_list_id>/items/<movie_id>")
@login_required
def add_custom_list_item(custom_list_id: str, movie_id: str):
    custom_list = MovieService.custom_list_for_owner(current_user.id, custom_list_id)
    movie = MovieRepository.get(movie_id)
    if custom_list is None or movie is None:
        abort(404)
    MovieService.add_to_custom_list(custom_list, movie)
    flash("Added to custom list.", "success")
    return redirect(url_for("movies.detail", movie_id=movie_id))


@bp.post("/items/<movie_id>/lists")
@login_required
def add_movie_to_selected_custom_list(movie_id: str):
    custom_list = MovieService.custom_list_for_owner(
        current_user.id, str(request.form.get("custom_list_id") or "")
    )
    movie = MovieRepository.get(movie_id)
    if custom_list is None or movie is None:
        abort(404)
    MovieService.add_to_custom_list(custom_list, movie)
    flash("Added to custom list.", "success")
    return redirect(url_for("movies.detail", movie_id=movie_id))


@bp.post("/lists/<custom_list_id>/items/<movie_id>/delete")
@login_required
def remove_custom_list_item(custom_list_id: str, movie_id: str):
    custom_list = MovieService.custom_list_for_owner(current_user.id, custom_list_id)
    if custom_list is None:
        abort(404)
    MovieService.remove_from_custom_list(custom_list, movie_id)
    flash("Removed from custom list.", "success")
    return redirect(url_for("movies.custom_lists"))


@bp.get("/browse/<media_type>")
@login_required
def browse(media_type: str):
    try:
        query, filter_errors = parse_browse_query(
            media_type,
            request.args,
            default_region=_movie_preferences()["preferred_region"],
        )
    except ValueError:
        abort(404)
    result = browse_catalog(query)
    return render_template(
        "movies/browse.html",
        active_module="movies",
        query=query,
        filter_errors=filter_errors,
        **result,
    )


@bp.get("/collections")
@login_required
def collections():
    return render_template(
        "movies/collections.html",
        active_module="movies",
        collections=active_movie_collections(),
    )


@bp.get("/collections/<collection_id>")
@login_required
def collection(collection_id: str):
    definition = movie_collection(collection_id)
    if definition is None:
        abort(404)
    query, result = collection_catalog(definition, request.args)
    return render_template(
        "movies/browse.html",
        active_module="movies",
        query=query,
        filter_errors={},
        collection=definition,
        **result,
    )


@bp.get("/shows")
@login_required
def shows():
    return redirect(
        url_for("movies.browse", media_type="tv", **request.args.to_dict(flat=True))
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


@bp.get("/api/what-should-i-watch")
@login_required
def api_what_should_i_watch():
    try:
        runtime_max = request.args.get("runtime_max", type=int)
        decade = request.args.get("decade", type=int)
        item = MovieService.what_should_i_watch(
            media_type=str(request.args.get("type") or ""),
            genre=str(request.args.get("genre") or ""),
            runtime_max=runtime_max,
            language=str(request.args.get("language") or ""),
            decade=decade,
            sort=str(request.args.get("sort") or "random"),
        )
    except ValueError as exc:
        return _api_error(str(exc))
    return jsonify({"ok": True, "item": item})


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
    if season_number < 0:
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
    movie = resolve_missing_tmdb_identity(movie)
    if movie.media_type == "tv":
        workspace = tv_show_workspace(movie)
        season_values = [
            int(item.get("season_number") or 0)
            for item in workspace["seasons"]
            if int(item.get("season_number") or 0) >= 0
            and int(item.get("episode_count") or 0) > 0
        ]
        requested_season = request.args.get("season", type=int)
        selected_season_number = (
            requested_season
            if requested_season in season_values
            else next(
                (value for value in season_values if value > 0),
                season_values[0] if season_values else None,
            )
        )
        selected_season_workspace = (
            tv_season_workspace(movie, season_number=selected_season_number)
            if selected_season_number is not None
            else None
        )
        return render_template(
            "movies/tv_show.html",
            active_module="movies",
            movie=movie_detail(movie),
            workspace=workspace,
            selected_season_workspace=selected_season_workspace,
            custom_lists=MovieService.custom_lists(current_user.id),
        )
    local_player_enabled = (
        current_app.config["DRAGON_PLAYBACK_ENABLED"]
        and current_app.config["DRAGON_MAGNETS_ENABLED"]
    )
    subtitles_enabled = (
        local_player_enabled
        and current_app.config["DRAGON_SUBTITLES_ENABLED"]
        and bool(
            current_app.config["DRAGON_WYZIE_API_KEY"] or current_app.config["DRAGON_SUBDL_API_KEY"]
        )
    )
    indexed_embed_sources = PlaybackService.indexed_embed_sources(
        movie_id,
        enabled_providers=_enabled_indexed_embed_providers(),
        provider_priorities=_provider_priorities(),
    )
    player_sources = PlaybackService.player_sources(movie_id) if local_player_enabled else []
    last_selected_source = PlaybackService.last_selected_source(movie_id)
    last_selected_source_id, last_selected_provider = _default_player_selection(
        last_selected_source, player_sources
    )
    embed_player_sources = _embed_player_sources(movie, indexed_embed_sources)
    movie_preferences = _movie_preferences()
    return render_template(
        "movies/detail.html",
        active_module="movies",
        movie=movie_detail(movie),
        score_options=_movie_score_options(),
        vidsrc_enabled=_vidsrc_is_usable_candidate(movie),
        local_player_enabled=local_player_enabled,
        subtitles_enabled=subtitles_enabled,
        player_sources=player_sources,
        indexed_embed_sources=indexed_embed_sources,
        embed_player_sources=embed_player_sources,
        indexed_provider_options=_indexed_provider_options(),
        last_selected_source_id=last_selected_source_id,
        last_selected_provider=last_selected_provider,
        jackett_eligible=_jackett_is_eligible(
            movie,
            indexed_embed_sources=indexed_embed_sources,
            player_sources=player_sources,
        ),
        jackett_search_available=_jackett_search_available(movie),
        custom_lists=MovieService.custom_lists(current_user.id),
        movie_preferences=movie_preferences,
    )


@bp.get("/<movie_id>/seasons/<int:season_number>")
@login_required
def tv_season(movie_id: str, season_number: int):
    movie = MovieRepository.get(movie_id)
    if movie is None or movie.media_type != "tv":
        abort(404)
    movie = resolve_missing_tmdb_identity(movie)
    if season_number < 0:
        abort(404)
    workspace = tv_season_workspace(movie, season_number=season_number)
    if not workspace["season"]["episode_count"]:
        abort(404)
    local_player_enabled = (
        current_app.config["DRAGON_PLAYBACK_ENABLED"]
        and current_app.config["DRAGON_MAGNETS_ENABLED"]
    )
    subtitles_enabled = (
        local_player_enabled
        and current_app.config["DRAGON_SUBTITLES_ENABLED"]
        and bool(
            current_app.config["DRAGON_WYZIE_API_KEY"] or current_app.config["DRAGON_SUBDL_API_KEY"]
        )
    )
    player_sources = workspace["player_sources"] if local_player_enabled else []
    indexed_embed_sources: list[dict] = []
    embed_player_sources = _embed_player_sources(movie, indexed_embed_sources)
    movie_preferences = _movie_preferences()
    return render_template(
        "movies/tv_season.html",
        active_module="movies",
        movie=movie_detail(movie),
        workspace=workspace,
        selected_episode=None,
        player_sources=player_sources,
        indexed_embed_sources=indexed_embed_sources,
        embed_player_sources=embed_player_sources,
        indexed_provider_options=[],
        last_selected_source_id="",
        last_selected_provider="",
        vidsrc_enabled=_vidsrc_is_usable_candidate(movie),
        local_player_enabled=local_player_enabled,
        subtitles_enabled=subtitles_enabled,
        jackett_eligible=_jackett_is_eligible(
            movie,
            indexed_embed_sources=indexed_embed_sources,
            player_sources=player_sources,
        ),
        jackett_search_available=_jackett_search_available(movie),
        movie_preferences=movie_preferences,
    )


@bp.get("/<movie_id>/seasons/<int:season_number>/episodes/<int:episode_number>")
@login_required
def tv_episode(movie_id: str, season_number: int, episode_number: int):
    movie = MovieRepository.get(movie_id)
    if movie is None or movie.media_type != "tv":
        abort(404)
    movie = resolve_missing_tmdb_identity(movie)
    if season_number < 0 or episode_number < 1:
        abort(404)
    workspace = tv_season_workspace(
        movie,
        season_number=season_number,
        selected_episode=episode_number,
    )
    if not workspace["selected_episode"]:
        abort(404)
    local_player_enabled = (
        current_app.config["DRAGON_PLAYBACK_ENABLED"]
        and current_app.config["DRAGON_MAGNETS_ENABLED"]
    )
    subtitles_enabled = (
        local_player_enabled
        and current_app.config["DRAGON_SUBTITLES_ENABLED"]
        and bool(
            current_app.config["DRAGON_WYZIE_API_KEY"] or current_app.config["DRAGON_SUBDL_API_KEY"]
        )
    )
    player_sources = workspace["player_sources"] if local_player_enabled else []
    indexed_embed_sources = PlaybackService.indexed_embed_sources(
        movie_id,
        season=season_number,
        episode=episode_number,
        enabled_providers=_enabled_indexed_embed_providers(),
        provider_priorities=_provider_priorities(),
    )
    last_selected_source = PlaybackService.last_selected_source(
        movie_id,
        season=season_number,
        episode=episode_number,
    )
    last_selected_source_id, last_selected_provider = _default_player_selection(
        last_selected_source, player_sources
    )
    embed_player_sources = _embed_player_sources(movie, indexed_embed_sources)
    movie_preferences = _movie_preferences()
    return render_template(
        "movies/tv_season.html",
        active_module="movies",
        movie=movie_detail(movie),
        workspace=workspace,
        selected_episode=workspace["selected_episode"],
        player_sources=player_sources,
        indexed_embed_sources=indexed_embed_sources,
        embed_player_sources=embed_player_sources,
        indexed_provider_options=_indexed_provider_options(),
        last_selected_source_id=last_selected_source_id,
        last_selected_provider=last_selected_provider,
        vidsrc_enabled=_vidsrc_is_usable_candidate(movie),
        local_player_enabled=local_player_enabled,
        subtitles_enabled=subtitles_enabled,
        jackett_eligible=_jackett_is_eligible(
            movie,
            indexed_embed_sources=indexed_embed_sources,
            player_sources=player_sources,
        ),
        jackett_search_available=_jackett_search_available(movie),
        movie_preferences=movie_preferences,
    )


@bp.get("/api/library/<movie_id>/seasons/<int:season_number>")
@login_required
def api_tv_season_workspace(movie_id: str, season_number: int):
    movie = MovieRepository.get(movie_id)
    if movie is None or movie.media_type != "tv":
        abort(404)
    if season_number < 0:
        return _api_error("Choose a valid season.")
    selected_episode = _optional_positive_int(request.args.get("episode"))
    workspace = tv_season_workspace(
        movie,
        season_number=season_number,
        selected_episode=selected_episode,
    )
    if not workspace["season"]["episode_count"]:
        return _api_error("Choose a valid season.", 404)
    return jsonify({"ok": True, "item": workspace})


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
    item["preview_player_sources"] = _discover_embed_player_sources(item)
    return render_template(
        "movies/discover.html",
        active_module="movies",
        media=item,
    )


@bp.get("/discover/<media_type>/<int:tmdb_id>/preview-source/<provider_key>")
@login_required
def discover_preview_source(media_type: str, tmdb_id: int, provider_key: str):
    """Resolve a configured TMDB-backed embed for a non-library preview.

    This endpoint deliberately does not call ``upsert_resolved_source``: a
    preview must not create library state, source rows, or progress records.
    """
    media_type = media_type.strip().lower()
    provider_key = provider_key.strip().lower()
    if media_type not in {"movie", "tv"} or tmdb_id < 1:
        abort(404)
    if not _playback_is_enabled():
        abort(404)
    registry = build_provider_registry_from_config(current_app.config)
    enabled = PlaybackService.enabled_provider_keys(registry.keys())
    allowed = {"vidsrc"} | {spec.key for spec in ID_CATALOG_EMBED_PROVIDER_SPECS}
    if provider_key not in allowed or provider_key not in enabled:
        return _api_error("The selected preview provider is not enabled.", 409)
    if provider_key == "vidsrc" and not current_app.config.get("DRAGON_VIDSRC_ENABLED"):
        return _api_error("VidSrc previews are disabled.", 409)

    try:
        season = _optional_positive_int(request.args.get("season"))
        episode = _optional_positive_int(request.args.get("episode"))
    except ValueError:
        return _api_error("Choose a valid season and episode.")
    if (season is None) != (episode is None):
        return _api_error("TV preview requires both a season and an episode.")
    if media_type == "tv" and (season is None or episode is None):
        return _api_error("Choose a season and episode before starting the preview.")
    if media_type == "movie" and (season is not None or episode is not None):
        return _api_error("Movie preview does not accept a season or episode.")

    provider = registry.get(provider_key)
    if provider is None:
        return _api_error("The selected preview provider is unavailable.", 409)
    identity = PlaybackIdentity(
        movie_id=f"preview:{media_type}:{tmdb_id}",
        tmdb_id=str(tmdb_id),
        media_type=media_type,
        season=season,
        episode=episode,
    )
    try:
        resolved = provider.resolve(identity)
    except ValueError as exc:
        return _api_error(str(exc), 503)
    response = jsonify({"ok": True, "preview": True, "source": resolved.response_item()})
    response.headers["Cache-Control"] = "private, no-store"
    return response


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
    score_option = score_option_for_input(
        raw_score,
        labels=[option.label for option in _movie_score_options()],
    )
    try:
        score = score_option.value if score_option else (float(raw_score) if raw_score else None)
        MovieService.set_score(movie, score, label=score_option.label if score_option else None)
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        notion_page_id = str((movie.external_ids or {}).get("notion_page_id") or "")
        if notion_page_id and current_app.config["DRAGON_NOTION_WRITEBACK_ENABLED"]:
            try:
                notion_movie_provider().set_score(
                    notion_page_id,
                    score_option.label if score_option else None,
                )
            except MediaIntegrationError as exc:
                flash(f"Personal score saved locally, but Notion could not update: {exc}", "error")
            else:
                flash("Personal score and Notion were updated.", "success")
        else:
            flash("Personal score updated.", "success")
    return redirect(url_for("movies.detail", movie_id=movie_id))


@bp.post("/<movie_id>/favorite")
@login_required
def update_favorite(movie_id: str):
    movie = MovieRepository.get(movie_id)
    if movie is None:
        abort(404)
    MovieService.set_favorite(movie, str(request.form.get("favorite") or "") == "1")
    flash("Favorite updated.", "success")
    return redirect(url_for("movies.detail", movie_id=movie_id))


@bp.post("/<movie_id>/refresh-metadata")
@login_required
def refresh_metadata(movie_id: str):
    movie = MovieRepository.get(movie_id)
    if movie is None:
        abort(404)
    try:
        refresh_movie_metadata(movie)
    except MediaIntegrationError as exc:
        flash(str(exc), "error")
    else:
        flash("TMDB detail metadata refreshed locally.", "success")
    return redirect(url_for("movies.detail", movie_id=movie_id))


@bp.post("/<movie_id>/seasons/<int:season_number>/episodes/<int:episode_number>/resolve-source")
@login_required
def resolve_tv_episode_source(movie_id: str, season_number: int, episode_number: int):
    movie = MovieRepository.get(movie_id)
    if movie is None or movie.media_type != "tv":
        abort(404)
    if season_number < 1 or episode_number < 1:
        abort(404)
    existing_sources = PlaybackService.tv_episode_sources(
        movie_id,
        season=season_number,
        episode=episode_number,
    )
    if existing_sources["exact"] or existing_sources["fallback"]:
        flash("A saved local source is already ready for this episode.", "success")
        return redirect(
            url_for(
                "movies.tv_episode",
                movie_id=movie_id,
                season_number=season_number,
                episode_number=episode_number,
            )
            + "#episode-player"
        )
    indexed_embed_sources = PlaybackService.indexed_embed_sources(
        movie_id,
        season=season_number,
        episode=episode_number,
        enabled_providers=_enabled_indexed_embed_providers(),
        provider_priorities=_provider_priorities(),
    )
    if not _jackett_is_eligible(
        movie,
        indexed_embed_sources=indexed_embed_sources,
        player_sources=[
            source
            for source in (existing_sources["exact"], existing_sources["fallback"])
            if source is not None
        ],
    ):
        flash(
            "A direct playback source is already available, so local source search was skipped.",
            "info",
        )
        return redirect(
            url_for(
                "movies.tv_episode",
                movie_id=movie_id,
                season_number=season_number,
                episode_number=episode_number,
            )
            + "#episode-player"
        )
    try:
        exact_lookup = release_lookup(
            media_type="tv",
            tmdb_id=int((movie.external_ids or {}).get("tmdb_id") or 0),
            season=season_number,
            episode=episode_number,
            mode="exact_episode",
        )
        release = next(iter(exact_lookup.get("items") or []), None)
        release_mode = "episode"
        if release is None:
            pack_lookup = release_lookup(
                media_type="tv",
                tmdb_id=int((movie.external_ids or {}).get("tmdb_id") or 0),
                season=season_number,
                episode=episode_number,
                mode="season_pack",
            )
            release = next(iter(pack_lookup.get("items") or []), None)
            release_mode = "season_pack"
        if release is None:
            flash("No exact episode or strong season-pack fallback was found.", "error")
            return redirect(
                url_for(
                    "movies.tv_episode",
                    movie_id=movie_id,
                    season_number=season_number,
                    episode_number=episode_number,
                )
            )
        import_release(
            media_type="tv",
            tmdb_id=int((movie.external_ids or {}).get("tmdb_id") or 0),
            magnet_uri=str(release.get("magnet_uri") or ""),
            release_title=str(release.get("title") or ""),
            tracker=str(release.get("tracker") or "Unknown tracker"),
            seeders=max(0, int(release.get("seeders") or 0)),
            size=max(0, int(release.get("size") or 0)),
            season=season_number,
            episode=episode_number,
            release_mode=release_mode,
        )
    except (MediaIntegrationError, ValueError) as exc:
        flash(str(exc), "error")
        return redirect(
            url_for(
                "movies.tv_episode",
                movie_id=movie_id,
                season_number=season_number,
                episode_number=episode_number,
            )
        )
    flash(
        "Saved the best exact episode source."
        if release_mode == "episode"
        else "Saved the best season-pack fallback for this episode.",
        "success",
    )
    return redirect(
        url_for(
            "movies.tv_episode",
            movie_id=movie_id,
            season_number=season_number,
            episode_number=episode_number,
        )
        + "#episode-player"
    )


def _optional_positive_int(value) -> int | None:
    if value in {None, ""}:
        return None
    parsed = int(value)
    if parsed < 1:
        raise ValueError
    return parsed


def _api_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": {"message": message}}), status
