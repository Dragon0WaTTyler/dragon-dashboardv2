from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from flask import current_app

from app.extensions import db
from app.movies.integrations import (
    JackettReleaseProvider,
    MediaIntegrationError,
    NotionMovieProvider,
    TmdbCatalogProvider,
)
from app.movies.models import Movie
from app.movies.repositories import MovieRepository
from app.playback.models import PlaybackSource


@dataclass(slots=True)
class LibrarySyncResult:
    library_ids: list[str] | None
    error: str = ""
    synced: bool = False


def tmdb_catalog_provider() -> TmdbCatalogProvider:
    provider = current_app.extensions.get("dragon_tmdb_catalog_provider")
    if provider is None:
        provider = TmdbCatalogProvider(
            api_key=current_app.config["DRAGON_TMDB_API_KEY"],
            read_access_token=current_app.config["DRAGON_TMDB_READ_ACCESS_TOKEN"],
        )
        current_app.extensions["dragon_tmdb_catalog_provider"] = provider
    return provider


def jackett_release_provider() -> JackettReleaseProvider:
    provider = current_app.extensions.get("dragon_jackett_release_provider")
    if provider is None:
        provider = JackettReleaseProvider(
            base_url=current_app.config["DRAGON_JACKETT_URL"],
            api_key=current_app.config["DRAGON_JACKETT_API_KEY"],
            min_seeders=current_app.config["DRAGON_JACKETT_MIN_SEEDERS"],
        )
        current_app.extensions["dragon_jackett_release_provider"] = provider
    return provider


def notion_movie_provider() -> NotionMovieProvider:
    provider = current_app.extensions.get("dragon_notion_movie_provider")
    if provider is None:
        provider = NotionMovieProvider(
            token=current_app.config["DRAGON_NOTION_TOKEN"],
            database_id=current_app.config["DRAGON_NOTION_DATABASE_ID"],
            data_source_id=current_app.config["DRAGON_NOTION_DATA_SOURCE_ID"],
        )
        current_app.extensions["dragon_notion_movie_provider"] = provider
    return provider


def sync_notion_library(*, force: bool = False) -> LibrarySyncResult:
    if not current_app.config["DRAGON_NOTION_SYNC_ENABLED"]:
        return LibrarySyncResult(library_ids=None)
    provider = notion_movie_provider()
    if not provider.configured:
        return LibrarySyncResult(
            library_ids=MovieRepository.notion_library_ids(),
            error="Notion credentials are not configured.",
        )

    cache = current_app.extensions.setdefault(
        "dragon_notion_movie_sync",
        {"expires_at": 0.0, "library_ids": [], "error": ""},
    )
    if not force and time.monotonic() < float(cache.get("expires_at") or 0):
        return LibrarySyncResult(
            library_ids=list(cache.get("library_ids") or []),
            error=str(cache.get("error") or ""),
        )
    try:
        items = provider.list_items()
        library_ids = [_upsert_notion_item(item).id for item in items]
        db.session.commit()
    except (MediaIntegrationError, ValueError) as exc:
        db.session.rollback()
        library_ids = list(cache.get("library_ids") or [])
        if not library_ids:
            library_ids = MovieRepository.notion_library_ids()
        cache.update(
            {
                "expires_at": time.monotonic() + 30,
                "library_ids": library_ids,
                "error": str(exc),
            }
        )
        return LibrarySyncResult(library_ids=library_ids, error=str(exc))

    cache.update(
        {
            "expires_at": time.monotonic()
            + current_app.config["DRAGON_NOTION_SYNC_TTL_SECONDS"],
            "library_ids": library_ids,
            "error": "",
        }
    )
    return LibrarySyncResult(library_ids=library_ids, synced=True)


def search_catalog(query: str, media_type: str) -> dict[str, Any]:
    sync = sync_notion_library()
    library_ids = sync.library_ids
    local_movies = _library_movies(library_ids)
    needle = _normalized(query)
    local_matches = [
        movie
        for movie in local_movies
        if needle in movie.normalized_title
        and (media_type == "all" or movie.media_type == media_type)
    ]
    discovery = tmdb_catalog_provider().search(query, media_type)
    by_tmdb = {
        (
            str((movie.external_ids or {}).get("tmdb_type") or movie.media_type),
            str((movie.external_ids or {}).get("tmdb_id") or ""),
        ): movie
        for movie in local_movies
    }
    by_title = {
        (movie.media_type, movie.normalized_title, movie.year): movie for movie in local_movies
    }
    results = []
    for item in discovery:
        movie = by_tmdb.get((item["media_type"], str(item["tmdb_id"])))
        if movie is None:
            movie = by_title.get(
                (item["media_type"], _normalized(item["title"]), item.get("year"))
            )
        results.append(
            {
                **item,
                "in_library": movie is not None,
                "local_id": movie.id if movie else None,
                "has_playback": _has_playback_source(movie) if movie else False,
                "detail_url": (
                    f"/movies/{movie.id}"
                    if movie
                    else f"/movies/discover/{item['media_type']}/{item['tmdb_id']}"
                ),
            }
        )
    return {
        "library": [_search_item(movie) for movie in local_matches],
        "discovery": results,
        "library_error": sync.error,
    }


def discover_item(media_type: str, tmdb_id: int) -> dict[str, Any]:
    sync = sync_notion_library()
    details = tmdb_catalog_provider().details(media_type, tmdb_id)
    movie = _match_library_movie(sync.library_ids, details)
    return {
        **details,
        "in_library": movie is not None,
        "local_id": movie.id if movie else None,
        "has_playback": _has_playback_source(movie) if movie else False,
        "detail_url": (
            f"/movies/{movie.id}"
            if movie
            else f"/movies/discover/{media_type}/{tmdb_id}"
        ),
        "library_error": sync.error,
    }


def add_to_library(
    *,
    media_type: str,
    tmdb_id: int,
    season: int | None = None,
) -> Movie:
    if not current_app.config["DRAGON_NOTION_WRITEBACK_ENABLED"]:
        raise MediaIntegrationError("Notion write-back is disabled.")
    details = tmdb_catalog_provider().details(media_type, tmdb_id)
    if media_type == "tv":
        season = season or 1
    notion_item = notion_movie_provider().upsert_media(
        details,
        season=season,
        episode=None,
        status="want_to_watch",
    )
    item = {
        **notion_item,
        **details,
        "notion_page_id": notion_item["notion_page_id"],
        "source": notion_item.get("source") or "Dragon",
        "status": notion_item.get("status") or "want_to_watch",
        "season": season,
        "episode": None,
        "release_title": "",
        "playback_sources": [],
    }
    movie = _upsert_notion_item(item)
    db.session.commit()
    _invalidate_sync_cache(movie.id)
    return movie


def import_release(
    *,
    media_type: str,
    tmdb_id: int,
    magnet_uri: str,
    release_title: str,
    tracker: str,
    seeders: int,
    size: int,
    season: int | None,
    episode: int | None,
    release_mode: str = "episode",
) -> Movie:
    if not current_app.config["DRAGON_NOTION_WRITEBACK_ENABLED"]:
        raise MediaIntegrationError("Notion write-back is disabled.")
    if release_mode not in {"episode", "season_pack"}:
        release_mode = "episode"
    if media_type == "tv" and not season:
        raise ValueError("Choose a season before importing a series release.")
    if media_type == "tv" and not episode and release_mode != "season_pack":
        raise ValueError("Choose an episode before importing this series release.")
    details = tmdb_catalog_provider().details(media_type, tmdb_id)
    notion_item = notion_movie_provider().upsert_media(
        details,
        magnet_uri=magnet_uri,
        release_title=release_title,
        season=season,
        episode=episode,
    )
    item = {
        **notion_item,
        **details,
        "notion_page_id": notion_item["notion_page_id"],
        "source": notion_item.get("source") or "Dragon",
        "status": notion_item.get("status") or "watching",
        "season": season,
        "episode": episode,
        "release_title": release_title,
        "playback_sources": [
            {
                "kind": "magnet",
                "label": _release_label(media_type, season, episode, release_mode),
                "locator": magnet_uri,
                "selected": True,
                "metadata": {
                    "origin": "jackett",
                    "release_mode": release_mode,
                    "season_pack": release_mode == "season_pack",
                    "tracker": tracker,
                    "seeders": seeders,
                    "size": size,
                    "release_title": release_title,
                    "season": season,
                    "episode": episode,
                },
            }
        ],
    }
    movie = _upsert_notion_item(item)
    db.session.commit()
    _invalidate_sync_cache(movie.id)
    return movie


def release_lookup(
    *,
    media_type: str,
    tmdb_id: int,
    season: int | None = None,
    episode: int | None = None,
    mode: str = "auto",
) -> dict[str, Any]:
    if mode not in {"auto", "exact_episode", "season_pack"}:
        mode = "auto"
    query_episode = None if mode == "season_pack" else episode
    details, queries, match_context = tmdb_catalog_provider().release_queries(
        media_type,
        tmdb_id,
        season=season,
        episode=query_episode,
    )
    releases = jackett_release_provider().search_many(
        queries,
        media_type,
        match_context=match_context,
        mode=mode,
    )
    return {
        "media": details,
        "queries": queries,
        "match_context": match_context,
        "items": releases,
    }


def writeback_watch(movie: Movie, *, started: bool) -> None:
    if not current_app.config["DRAGON_NOTION_WRITEBACK_ENABLED"]:
        return
    notion_page_id = str((movie.external_ids or {}).get("notion_page_id") or "")
    if not notion_page_id:
        return
    notion_movie_provider().mark_watched(notion_page_id, started=started)


def _upsert_notion_item(item: dict) -> Movie:
    all_movies = list(db.session.scalars(db.select(Movie)))
    notion_page_id = str(item.get("notion_page_id") or "")
    tmdb_id = str(item.get("tmdb_id") or "")
    movie = next(
        (
            candidate
            for candidate in all_movies
            if notion_page_id
            and str((candidate.external_ids or {}).get("notion_page_id") or "")
            == notion_page_id
        ),
        None,
    )
    if movie is None and tmdb_id:
        movie = next(
            (
                candidate
                for candidate in all_movies
                if str((candidate.external_ids or {}).get("tmdb_id") or "") == tmdb_id
                and str(
                    (candidate.external_ids or {}).get("tmdb_type")
                    or candidate.media_type
                )
                == item.get("media_type")
            ),
            None,
        )
    normalized = _normalized(item.get("title"))
    if movie is None:
        movie = next(
            (
                candidate
                for candidate in all_movies
                if candidate.normalized_title == normalized
                and candidate.year == item.get("year")
            ),
            None,
        )
    if movie is None:
        movie = Movie(title=str(item.get("title") or "Untitled"), normalized_title=normalized)
        db.session.add(movie)
        db.session.flush()

    movie.title = str(item.get("title") or movie.title)
    movie.normalized_title = normalized or movie.normalized_title
    movie.original_title = item.get("original_title") or movie.original_title
    movie.media_type = str(item.get("media_type") or "movie")
    movie.year = item.get("year") if item.get("year") is not None else movie.year
    movie.runtime_minutes = item.get("runtime_minutes") or movie.runtime_minutes
    movie.status = str(item.get("status") or movie.status or "unknown")
    if item.get("personal_score") is not None:
        movie.personal_score = item["personal_score"]
    movie.category = str(
        item.get("category") or ("movie" if movie.media_type == "movie" else "tv show")
    )
    movie.source = str(item.get("source") or "Notion")
    movie.overview = str(item.get("overview") or movie.overview or "")
    movie.poster_url = str(item.get("poster_url") or movie.poster_url or "")
    if item.get("genres"):
        movie.genres = list(item["genres"])
    if item.get("directors"):
        movie.directors = list(item["directors"])
    if item.get("cast"):
        movie.cast = list(item["cast"])
    movie.external_ids = {
        **dict(movie.external_ids or {}),
        **dict(item.get("external_ids") or {}),
        "notion_page_id": notion_page_id,
        **({"tmdb_id": tmdb_id, "tmdb_type": movie.media_type} if tmdb_id else {}),
    }
    movie.metadata_state = {
        **dict(movie.metadata_state or {}),
        "library_origin": "notion",
        "notion_last_edited_time": item.get("last_edited_time"),
        "season": item.get("season"),
        "episode": item.get("episode"),
        "release_title": item.get("release_title"),
    }
    _upsert_playback_sources(movie, item.get("playback_sources") or [])
    return movie


def _upsert_playback_sources(movie: Movie, sources: list[dict]) -> None:
    if any(source.get("selected") for source in sources):
        for current in db.session.scalars(
            db.select(PlaybackSource).where(PlaybackSource.movie_id == movie.id)
        ):
            current.selected = False
    for source in sources:
        locator = str(source.get("locator") or "").strip()
        kind = str(source.get("kind") or "")
        if not locator or kind not in {"magnet", "torrent"}:
            continue
        existing = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie.id,
                PlaybackSource.kind == kind,
                PlaybackSource.locator == locator,
            )
        )
        if existing is None:
            existing = PlaybackSource(movie_id=movie.id, kind=kind, locator=locator)
            db.session.add(existing)
        existing.label = str(source.get("label") or f"Imported {kind}")[:300]
        existing.status = "available"
        existing.selected = bool(source.get("selected", existing.selected))
        existing.metadata_json = {
            **dict(existing.metadata_json or {}),
            **dict(source.get("metadata") or {}),
            "origin": dict(source.get("metadata") or {}).get("origin", "notion"),
        }


def _library_movies(library_ids: list[str] | None) -> list[Movie]:
    query = db.select(Movie)
    if library_ids is not None:
        query = query.where(Movie.id.in_(library_ids))
    return list(db.session.scalars(query))


def _search_item(movie: Movie) -> dict:
    return {
        "local_id": movie.id,
        "tmdb_id": (movie.external_ids or {}).get("tmdb_id"),
        "media_type": movie.media_type,
        "title": movie.title,
        "year": movie.year,
        "poster_url": movie.poster_url,
        "overview": movie.overview,
        "in_library": True,
        "has_playback": _has_playback_source(movie),
        "detail_url": f"/movies/{movie.id}",
    }


def _has_playback_source(movie: Movie | None) -> bool:
    if movie is None:
        return False
    return (
        db.session.scalar(
            db.select(PlaybackSource.id)
            .where(
                PlaybackSource.movie_id == movie.id,
                PlaybackSource.kind.in_(("magnet", "torrent")),
            )
            .limit(1)
        )
        is not None
    )


def _release_label(
    media_type: str,
    season: int | None,
    episode: int | None,
    release_mode: str = "episode",
) -> str:
    if media_type == "tv" and season and release_mode == "season_pack":
        return f"S{season:02d} season pack Jackett magnet"
    if media_type == "tv" and season and not episode:
        return f"S{season:02d} season pack Jackett magnet"
    if media_type == "tv" and season and episode:
        return f"S{season:02d}E{episode:02d} Jackett magnet"
    return "Jackett magnet"


def _match_library_movie(library_ids: list[str] | None, item: dict[str, Any]) -> Movie | None:
    local_movies = _library_movies(library_ids)
    tmdb_id = str(item.get("tmdb_id") or "")
    for movie in local_movies:
        if (
            tmdb_id
            and str((movie.external_ids or {}).get("tmdb_id") or "") == tmdb_id
            and str((movie.external_ids or {}).get("tmdb_type") or movie.media_type)
            == str(item.get("media_type") or "")
        ):
            return movie
    normalized = _normalized(item.get("title"))
    year = item.get("year")
    for movie in local_movies:
        if movie.normalized_title == normalized and movie.year == year:
            return movie
    return None


def _invalidate_sync_cache(movie_id: str) -> None:
    cache = current_app.extensions.get("dragon_notion_movie_sync")
    if not isinstance(cache, dict):
        return
    ids = list(cache.get("library_ids") or [])
    if movie_id not in ids:
        ids.append(movie_id)
    cache.update({"library_ids": ids, "expires_at": 0.0, "error": ""})


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())
