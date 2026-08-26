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
    hydrate_missing_recommendation_overviews,
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
from app.movies.rails import discovery_rails
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
from app.playback.providers import (
    ID_CATALOG_EMBED_PROVIDER_SPECS,
    build_provider_registry_from_config,
)
from app.playback.services import PlaybackService

bp = Blueprint("movies", __name__, url_prefix="/movies")


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


@bp.get("")
@login_required
def index():
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
    hydrate_missing_recommendation_overviews()
    movies, total = MovieRepository.list(
        filters,
        limit=per_page,
        offset=offset,
        library_ids=library_sync.library_ids,
    )
    continue_items = [
        movie_item(movie)
        for movie in MovieRepository.continue_watching(library_ids=library_sync.library_ids)
    ]
    want_to_watch = [
        movie_item(movie)
        for movie in MovieRepository.watch_next(limit=12, library_ids=library_sync.library_ids)
    ]
    personal_pick = MovieService.what_should_i_watch()
    because_you_watched = MovieService.because_you_watched()
    recommendations = MovieService.recommendation_pool(
        category=filters["category"], source=filters["source"]
    )["items"]
    recommendation = recommendations[0] if recommendations else None
    home_focus = continue_items[0] if continue_items else personal_pick or recommendation
    home_focus_kind = (
        "resume" if continue_items else "personal" if personal_pick else "recommendation"
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
        continue_watching=continue_items,
        want_to_watch=want_to_watch,
        home_focus=home_focus,
        home_focus_kind=home_focus_kind,
        personal_pick=personal_pick,
        because_you_watched=because_you_watched,
        discovery_rails=discovery_rails(),
        recommendation=recommendation,
        recommendations=recommendations,
        movie_preferences=preferences,
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
        return render_template(
            "movies/tv_show.html",
            active_module="movies",
            movie=movie_detail(movie),
            workspace=tv_show_workspace(movie),
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
