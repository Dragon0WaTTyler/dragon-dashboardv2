from __future__ import annotations

import re
from datetime import datetime, timezone
from random import SystemRandom
from typing import Any

UTC = getattr(datetime, "UTC", timezone.utc)

from sqlalchemy import case, func
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.history.services import HistoryService
from app.movies.models import (
    Movie,
    MovieCustomList,
    MovieCustomListItem,
    MovieLibraryEntry,
    MovieProgress,
    canonical_media_key,
)
from app.movies.scoring import score_option_for_input
from app.playback.models import PlaybackSource
from app.shared.time import utc_now

UTC = timezone.utc  # noqa: UP017 - keep Python 3.10 compatibility

MOVIE_STATUSES = {"want_to_watch", "watching", "finished", "watched", "unknown"}
MOVIE_COMPLETION_THRESHOLD = 0.95
EPISODE_COMPLETION_THRESHOLD = 0.90
SORT_VALUES = {"title_asc", "title_desc", "score_desc", "year_desc", "recently_updated"}
WHAT_TO_WATCH_SORTS = {"random", "oldest_added", "recently_added"}
VALID_MOVIE_CATEGORIES = {
    "movie",
    "tv show",
    "anime",
    "short movie",
    "documentary",
    "theatre",
}
TITLE_NOISE_TOKENS = (
    "1080p",
    "720p",
    "2160p",
    "bluray",
    "brrip",
    "webrip",
    "web-dl",
    "hdrip",
    "x264",
    "x265",
    "yify",
    "dvdrip",
)


class ProgressConflictError(ValueError):
    def __init__(self, progress: dict[str, Any]):
        super().__init__("A newer progress update is already stored.")
        self.progress = progress


def lifecycle_status_for(value: str | None) -> str:
    """Map legacy Movie status strings to the V2 lifecycle contract."""

    value = str(value or "").strip().lower()
    if value in {"finished", "watched"}:
        return "watched"
    if value == "watching":
        return "watching"
    return "want_to_watch"


def effective_lifecycle_status(movie: Movie) -> str:
    if movie.library_entry:
        return movie.library_entry.lifecycle_status
    return lifecycle_status_for(movie.status)


def effective_personal_rating(movie: Movie) -> float | None:
    return movie.library_entry.personal_rating if movie.library_entry else movie.personal_score


def effective_personal_label(movie: Movie) -> str:
    if movie.library_entry:
        return movie.library_entry.personal_label
    return str(dict(movie.metadata_state or {}).get("personal_score_label") or "")


def lifecycle_status_sql():
    return case(
        (MovieLibraryEntry.lifecycle_status.is_not(None), MovieLibraryEntry.lifecycle_status),
        (Movie.status.in_(("finished", "watched")), "watched"),
        (Movie.status == "watching", "watching"),
        else_="want_to_watch",
    )


def completion_threshold(*, season: int | None = None, episode: int | None = None) -> float:
    if season is not None or episode is not None:
        return EPISODE_COMPLETION_THRESHOLD
    return MOVIE_COMPLETION_THRESHOLD


def progress_is_completed(
    *,
    current_seconds: int,
    duration_seconds: int,
    ended: bool = False,
    season: int | None = None,
    episode: int | None = None,
) -> bool:
    if ended:
        return True
    if duration_seconds <= 0:
        return False
    threshold = completion_threshold(season=season, episode=episode)
    return current_seconds / duration_seconds >= threshold


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None


def _utc_json(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _utc_sort_key(value: datetime | None) -> datetime:
    """Return a comparable UTC timestamp for legacy and current Movie rows."""

    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def progress_dict(progress: MovieProgress | None) -> dict[str, Any] | None:
    if progress is None:
        return None
    percent = 0
    if progress.duration_seconds > 0:
        percent = min(100, round(progress.current_seconds / progress.duration_seconds * 100))
    return {
        "season": progress.season,
        "episode": progress.episode,
        "current_seconds": progress.current_seconds,
        "duration_seconds": progress.duration_seconds,
        "percent": percent,
        "completed": progress.completed,
        "remaining_seconds": max(0, progress.duration_seconds - progress.current_seconds),
        "updated_at": _utc_json(progress.updated_at),
    }


def _display_progress(movie: Movie) -> MovieProgress | None:
    entries = list(movie.progress_entries or [])
    if entries:
        return entries[0]
    return movie.progress


def _watch_target(progress: MovieProgress | None) -> dict[str, Any] | None:
    if progress is None or not progress.season or not progress.episode:
        return None
    completed = bool(
        progress.completed
        or progress_is_completed(
            current_seconds=progress.current_seconds,
            duration_seconds=progress.duration_seconds,
            season=progress.season,
            episode=progress.episode,
        )
    )
    episode = int(progress.episode) + 1 if completed else int(progress.episode)
    return {
        "season": int(progress.season),
        "episode": episode,
        "from_completed_episode": completed,
    }


def movie_item(movie: Movie) -> dict[str, Any]:
    progress = _display_progress(movie)
    metadata_state = dict(movie.metadata_state or {})
    tmdb_detail = metadata_state.get("tmdb_detail")
    tmdb_detail = dict(tmdb_detail) if isinstance(tmdb_detail, dict) else {}
    score_option = score_option_for_input(
        effective_personal_rating(movie),
        stored_label=effective_personal_label(movie),
    )
    return {
        "id": movie.id,
        "media_key": movie.media_key,
        "title": movie.title,
        "media_type": movie.media_type,
        "year": movie.year,
        "runtime_minutes": movie.runtime_minutes,
        "status": effective_lifecycle_status(movie),
        "personal_score": effective_personal_rating(movie),
        "personal_score_label": score_option.label if score_option else None,
        "is_favorite": bool(movie.library_entry and movie.library_entry.is_favorite),
        "poster_url": movie.poster_url,
        # These are already persisted catalog fields.  Keeping them on the
        # lightweight view model lets the Movies surface render artwork-first
        # cards without changing any library or playback contract.
        "overview": movie.overview,
        "genres": list(movie.genres or []),
        "genre_names": _entry_names(movie.genres),
        "backdrop_url": str(tmdb_detail.get("backdrop_url") or ""),
        "progress": progress_dict(progress),
        "watch_target": _watch_target(progress),
    }


def movie_detail(movie: Movie) -> dict[str, Any]:
    metadata_state = dict(movie.metadata_state or {})
    tmdb_detail = metadata_state.get("tmdb_detail")
    tmdb_detail = dict(tmdb_detail) if isinstance(tmdb_detail, dict) else {}
    trailers = []
    for trailer in tmdb_detail.get("trailers") or []:
        item = dict(trailer)
        url = str(item.get("url") or "")
        key = url.split("v=", 1)[1].split("&", 1)[0] if "v=" in url else ""
        if key:
            item["thumbnail_url"] = f"https://img.youtube.com/vi/{key}/hqdefault.jpg"
        trailers.append(item)
    return {
        **movie_item(movie),
        "original_title": movie.original_title,
        "media_type": movie.media_type,
        "runtime_minutes": movie.runtime_minutes,
        "category": movie.category,
        "source": movie.source,
        "overview": movie.overview,
        "trailer_url": movie.trailer_url or None,
        "genres": list(movie.genres or []),
        "directors": list(movie.directors or []),
        "cast": list(movie.cast or []),
        "watch_history": list(movie.watch_history or []),
        "external_ids": dict(movie.external_ids or {}),
        "metadata_state": metadata_state,
        "backdrop_url": str(tmdb_detail.get("backdrop_url") or ""),
        "tagline": str(tmdb_detail.get("tagline") or ""),
        "original_language": str(tmdb_detail.get("original_language") or ""),
        "countries": list(tmdb_detail.get("countries") or []),
        "certification": str(tmdb_detail.get("certification") or ""),
        "tmdb_rating": tmdb_detail.get("tmdb_rating"),
        "trailers": trailers,
        "reviews": list(tmdb_detail.get("reviews") or []),
        "similar": list(tmdb_detail.get("similar") or []),
        "recommendations": list(tmdb_detail.get("recommendations") or []),
        "provider_availability": list(metadata_state.get("provider_availability") or []),
        "updated_at": _utc_json(movie.updated_at),
    }


def tv_catalog(movie: Movie) -> dict[str, Any]:
    metadata = dict(movie.metadata_state or {})
    seasons = metadata.get("tv_seasons")
    episodes = metadata.get("tv_episodes")
    return {
        "total_seasons": int(metadata.get("tv_total_seasons") or 0),
        "total_episodes": int(metadata.get("tv_total_episodes") or 0),
        "seasons": list(seasons) if isinstance(seasons, list) else [],
        "episodes": dict(episodes) if isinstance(episodes, dict) else {},
        "show_notion_page_id": str(metadata.get("tv_show_notion_page_id") or ""),
        "show_notion_url": str(metadata.get("tv_show_notion_url") or ""),
    }


def _tv_progress_lookup(movie: Movie) -> dict[tuple[int, int], MovieProgress]:
    lookup: dict[tuple[int, int], MovieProgress] = {}
    for progress in movie.progress_entries or []:
        if progress.season is not None and progress.episode is not None:
            lookup[(int(progress.season), int(progress.episode))] = progress
    return lookup


def _tv_source_lookup(movie: Movie) -> dict[tuple[int, int], dict[str, PlaybackSource | None]]:
    rows = list(
        db.session.scalars(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie.id,
                PlaybackSource.kind == "magnet",
                PlaybackSource.status == "available",
            )
        )
    )
    catalog = tv_catalog(movie)
    season_episodes: dict[int, list[int]] = {}
    for season_key, episode_rows in (catalog.get("episodes") or {}).items():
        season_number = int(season_key)
        season_episodes[season_number] = [
            int(row.get("episode_number") or 0)
            for row in episode_rows or []
            if int(row.get("episode_number") or 0) > 0
        ]
    lookup: dict[tuple[int, int], dict[str, PlaybackSource | None]] = {}
    for row in rows:
        metadata = dict(row.metadata_json or {})
        season = _optional_int(row.season)
        if season is None:
            season = _optional_int(metadata.get("season"))
        if season is None:
            continue
        episode = _optional_int(row.episode)
        if episode is None:
            episode = _optional_int(metadata.get("episode"))
        source_role = str(row.source_role or metadata.get("source_role") or "")
        season_pack = bool(
            metadata.get("season_pack")
            or source_role == "season_pack_fallback"
            or str(metadata.get("release_mode") or "") == "season_pack"
        )
        target_episodes = (
            season_episodes.get(season, [])
            if season_pack
            else ([episode] if episode is not None else [])
        )
        for target_episode in target_episodes:
            key = (season, int(target_episode))
            bucket = lookup.setdefault(key, {"exact": None, "fallback": None})
            if season_pack:
                bucket["fallback"] = row
            elif source_role == "exact_episode":
                bucket["exact"] = row
            elif bucket["exact"] is None:
                bucket["exact"] = row
    return lookup


def _progress_completed(progress: dict[str, Any] | None) -> bool:
    if not progress:
        return False
    return bool(progress.get("completed") or int(progress.get("percent") or 0) >= 92)


def _episode_position(season: int | None, episode: int | None) -> tuple[int, int] | None:
    if not season or not episode:
        return None
    return (int(season), int(episode))


def _tv_furthest_position(
    movie: Movie,
    *,
    catalog: dict[str, Any],
    progress_lookup: dict[tuple[int, int], MovieProgress],
) -> tuple[int, int] | None:
    episode_keys: set[tuple[int, int]] = set()
    for season in catalog["seasons"]:
        season_number = int(season.get("season_number") or 0)
        if season_number < 1:
            continue
        for row in catalog["episodes"].get(str(season_number)) or []:
            episode_number = int(row.get("episode_number") or 0)
            if episode_number > 0:
                episode_keys.add((season_number, episode_number))

    candidates: list[tuple[int, int]] = []
    metadata_key = _episode_position(
        (movie.metadata_state or {}).get("season"),
        (movie.metadata_state or {}).get("episode"),
    )
    if metadata_key and metadata_key in episode_keys:
        candidates.append(metadata_key)

    for key, progress in progress_lookup.items():
        if key not in episode_keys:
            continue
        progress_data = progress_dict(progress)
        if _progress_completed(progress_data) or int(progress.current_seconds or 0) > 0:
            candidates.append(key)

    return max(candidates) if candidates else None


def _tv_effective_progress(
    *,
    season_number: int,
    episode_number: int,
    progress_lookup: dict[tuple[int, int], MovieProgress],
    furthest_position: tuple[int, int] | None,
) -> dict[str, Any] | None:
    key = (int(season_number), int(episode_number))
    explicit = progress_dict(progress_lookup.get(key))
    if season_number == 0:
        return explicit
    if furthest_position and key < furthest_position:
        return {
            "season": season_number,
            "episode": episode_number,
            "current_seconds": 0,
            "duration_seconds": 0,
            "percent": 100,
            "completed": True,
            "updated_at": explicit.get("updated_at") if explicit else None,
            "inferred": True,
        }
    return explicit


def _tv_resume_target(
    movie: Movie,
    *,
    catalog: dict[str, Any],
    progress_lookup: dict[tuple[int, int], MovieProgress],
) -> dict[str, Any] | None:
    episode_index: dict[tuple[int, int], dict[str, Any]] = {}
    for season in catalog["seasons"]:
        season_number = int(season.get("season_number") or 0)
        if season_number < 1:
            continue
        for row in catalog["episodes"].get(str(season_number)) or []:
            episode_number = int(row.get("episode_number") or 0)
            if episode_number < 1:
                continue
            episode_index[(season_number, episode_number)] = row

    latest_partial: dict[str, Any] | None = None
    for progress in movie.progress_entries or []:
        if not progress.season or not progress.episode:
            continue
        if progress.completed or progress.current_seconds <= 0:
            continue
        row = episode_index.get((int(progress.season), int(progress.episode)))
        percent = progress_dict(progress)
        latest_partial = {
            "season": int(progress.season),
            "episode": int(progress.episode),
            "name": str((row or {}).get("name") or f"Episode {progress.episode}"),
            "progress": percent,
            "mode": "resume",
        }
        break

    metadata_season = int((movie.metadata_state or {}).get("season") or 0)
    metadata_episode = int((movie.metadata_state or {}).get("episode") or 0)
    metadata_waypoint: dict[str, Any] | None = None
    if metadata_season > 0 and metadata_episode > 0:
        row = episode_index.get((metadata_season, metadata_episode))
        if row is not None:
            metadata_waypoint = {
                "season": metadata_season,
                "episode": metadata_episode,
                "name": str(row.get("name") or f"Episode {metadata_episode}"),
                "progress": progress_dict(progress_lookup.get((metadata_season, metadata_episode))),
                "mode": "current",
            }

    if latest_partial and metadata_waypoint:
        partial_key = (int(latest_partial["season"]), int(latest_partial["episode"]))
        metadata_key = (int(metadata_waypoint["season"]), int(metadata_waypoint["episode"]))
        if metadata_key > partial_key:
            return metadata_waypoint
        return latest_partial
    if metadata_waypoint:
        return metadata_waypoint
    if latest_partial:
        return latest_partial

    for season in catalog["seasons"]:
        season_number = int(season.get("season_number") or 0)
        if season_number < 1:
            continue
        for row in catalog["episodes"].get(str(season_number)) or []:
            episode_number = int(row.get("episode_number") or 0)
            if episode_number < 1:
                continue
            progress_data = progress_dict(progress_lookup.get((season_number, episode_number)))
            if not progress_data or not progress_data["completed"]:
                return {
                    "season": season_number,
                    "episode": episode_number,
                    "name": str(row.get("name") or f"Episode {episode_number}"),
                    "progress": progress_data,
                    "mode": "next",
                }
    return None


def _tv_next_normal_episode(
    catalog: dict[str, Any], *, season_number: int, episode_number: int
) -> dict[str, Any] | None:
    """Return the next catalogued normal episode without crossing through Specials."""

    current_key = (int(season_number), int(episode_number))
    candidates: list[dict[str, Any]] = []
    for season in sorted(
        catalog["seasons"], key=lambda item: int(item.get("season_number") or 0)
    ):
        candidate_season = int(season.get("season_number") or 0)
        if candidate_season < 1:
            continue
        for row in sorted(
            catalog["episodes"].get(str(candidate_season)) or [],
            key=lambda item: int(item.get("episode_number") or 0),
        ):
            candidate_episode = int(row.get("episode_number") or 0)
            if candidate_episode < 1 or (candidate_season, candidate_episode) <= current_key:
                continue
            candidates.append(
                {**row, "season_number": candidate_season, "episode_number": candidate_episode}
            )
    return candidates[0] if candidates else None


def tv_show_workspace(movie: Movie) -> dict[str, Any]:
    catalog = tv_catalog(movie)
    progress_lookup = _tv_progress_lookup(movie)
    source_lookup = _tv_source_lookup(movie)
    furthest_position = _tv_furthest_position(
        movie,
        catalog=catalog,
        progress_lookup=progress_lookup,
    )
    completed_seasons = 0
    watched_episodes = 0
    watched_specials = 0
    seasons: list[dict[str, Any]] = []

    for season in catalog["seasons"]:
        season_number = int(season.get("season_number") or 0)
        if season_number < 0:
            continue
        episode_rows = list(catalog["episodes"].get(str(season_number)) or [])
        completed_count = 0
        available_count = 0
        for row in episode_rows:
            episode_number = int(row.get("episode_number") or 0)
            if episode_number < 1:
                continue
            progress_data = _tv_effective_progress(
                season_number=season_number,
                episode_number=episode_number,
                progress_lookup=progress_lookup,
                furthest_position=furthest_position,
            )
            if _progress_completed(progress_data):
                completed_count += 1
                if season_number == 0:
                    watched_specials += 1
                else:
                    watched_episodes += 1
            if source_lookup.get((season_number, episode_number), {}).get("exact") or source_lookup.get((season_number, episode_number), {}).get("fallback"):
                available_count += 1
        episode_count = max(len([row for row in episode_rows if int(row.get("episode_number") or 0) > 0]), int(season.get("episode_count") or 0))
        if season_number > 0 and episode_count and completed_count >= episode_count:
            completed_seasons += 1
        seasons.append(
            {
                **season,
                "season_number": season_number,
                "is_specials": season_number == 0,
                "episode_count": episode_count,
                "completed_episode_count": completed_count,
                "available_episode_count": available_count,
                "completion_percent": min(100, round(completed_count / episode_count * 100)) if episode_count else 0,
                "is_completed": bool(episode_count and completed_count >= episode_count),
            }
        )

    resume_target = _tv_resume_target(movie, catalog=catalog, progress_lookup=progress_lookup)
    return {
        "show": movie_item(movie),
        "catalog": catalog,
        "seasons": seasons,
        "completed_seasons": completed_seasons,
        "watched_episodes": watched_episodes,
        "watched_specials": watched_specials,
        "resume_target": resume_target,
    }


def tv_season_workspace(movie: Movie, *, season_number: int, selected_episode: int | None = None) -> dict[str, Any]:
    catalog = tv_catalog(movie)
    progress_lookup = _tv_progress_lookup(movie)
    source_lookup = _tv_source_lookup(movie)
    furthest_position = _tv_furthest_position(
        movie,
        catalog=catalog,
        progress_lookup=progress_lookup,
    )
    resume_target = _tv_resume_target(movie, catalog=catalog, progress_lookup=progress_lookup)
    season_entry = next(
        (
            item
            for item in catalog["seasons"]
            if int(item.get("season_number") or 0) == int(season_number)
        ),
        None,
    )
    episode_rows = list(catalog["episodes"].get(str(season_number)) or [])
    episodes: list[dict[str, Any]] = []
    watched_count = 0
    selected = None

    for row in episode_rows:
        episode_number = int(row.get("episode_number") or 0)
        if episode_number < 1:
            continue
        progress = _tv_effective_progress(
            season_number=season_number,
            episode_number=episode_number,
            progress_lookup=progress_lookup,
            furthest_position=furthest_position,
        )
        if _progress_completed(progress):
            watched_count += 1
        sources = source_lookup.get((season_number, episode_number), {})
        item = {
            **row,
            "episode_number": episode_number,
            "progress": progress,
            "has_exact_source": bool(sources.get("exact")),
            "has_fallback_source": bool(sources.get("fallback")),
            "has_local_source": bool(sources.get("exact") or sources.get("fallback")),
        }
        episodes.append(item)
        if selected_episode == episode_number:
            selected = item

    if selected is None and episodes:
        selected = next(
            (item for item in episodes if not _progress_completed(item.get("progress"))),
            episodes[0],
        )
        selected_episode = int(selected["episode_number"])

    player_sources: list[dict[str, Any]] = []
    if selected_episode:
        from app.playback.services import PlaybackService

        player_sources = PlaybackService.tv_episode_player_sources(
            movie.id,
            season=season_number,
            episode=selected_episode,
        )

    season_progress = min(100, round(watched_count / len(episodes) * 100)) if episodes else 0
    next_episode = (
        _tv_next_normal_episode(
            catalog,
            season_number=season_number,
            episode_number=selected_episode,
        )
        if selected_episode and season_number > 0
        else None
    )
    return {
        "show": movie_item(movie),
        "catalog": catalog,
        "season": {
            **dict(season_entry or {}),
            "season_number": season_number,
            "episode_count": len(episodes) or int((season_entry or {}).get("episode_count") or 0),
            "watched_episode_count": watched_count,
            "completion_percent": season_progress,
        },
        "episodes": episodes,
        "selected_episode": selected,
        "selected_episode_number": selected_episode,
        "next_episode": next_episode,
        "resume_target": (
            resume_target
            if resume_target and int(resume_target.get("season") or 0) == int(season_number)
            else None
        ),
        "player_sources": player_sources,
    }


def _entry_names(entries: list[dict] | None) -> list[str]:
    names: list[str] = []
    for entry in entries or []:
        value = entry.get("name") if isinstance(entry, dict) else entry
        name = " ".join(str(value or "").split())
        if name:
            names.append(name)
    return names


def _normalized_key(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _metadata_quality(movie: Movie) -> dict[str, Any]:
    fields = {
        "poster": bool(movie.poster_url),
        "year": movie.year is not None,
        "director": bool(_entry_names(movie.directors)),
        "genres": bool(_entry_names(movie.genres)),
        "runtime": movie.runtime_minutes is not None,
        "overview": bool(movie.overview.strip()),
    }
    missing = [name for name, present in fields.items() if not present]
    score = len(fields) - len(missing)
    return {
        "score": score,
        "maximum": len(fields),
        "missing": missing,
        "is_clean": len(missing) <= 1,
        "is_weak": len(missing) >= 4,
    }


def _title_has_noise(title: str) -> bool:
    lowered = title.casefold()
    if any(token in lowered for token in TITLE_NOISE_TOKENS):
        return True
    if any(token in lowered for token in "[]{}"):
        return True
    return bool(
        re.search(r"\b(s\d{1,2}e\d{1,2}|season\s*\d+|episode\s*\d+|ep\.?\s*\d+)\b", lowered)
    )


def _source_priority(source: str) -> int:
    normalized = _normalized_key(source)
    if normalized == "my library and ebert's":
        return 3
    if normalized in {"my library", "ebert's library"}:
        return 2
    return 1


def _recommendation_profile(movies: list[Movie]) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "liked_count": 0,
        "strong_count": 0,
        "directors": {},
        "genres": {},
        "sources": {},
    }
    for movie in movies:
        score = float(movie.personal_score or 0)
        if score < 5:
            continue
        profile["liked_count"] += 1
        if score >= 7:
            profile["strong_count"] += 1
        for name in _entry_names(movie.directors):
            key = _normalized_key(name)
            bucket = profile["directors"].setdefault(key, {"count": 0, "titles": []})
            bucket["count"] += 1
            if score >= 7 and movie.title not in bucket["titles"]:
                bucket["titles"].append(movie.title)
                bucket["titles"] = bucket["titles"][:3]
        for name in _entry_names(movie.genres):
            key = _normalized_key(name)
            bucket = profile["genres"].setdefault(key, {"count": 0, "titles": []})
            bucket["count"] += 1
            if score >= 6 and movie.title not in bucket["titles"]:
                bucket["titles"].append(movie.title)
                bucket["titles"] = bucket["titles"][:3]
        source = _normalized_key(movie.source)
        if source:
            profile["sources"][source] = profile["sources"].get(source, 0) + 1
    return profile


def _recommendation_explanation(
    movie: Movie,
    profile: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    signals: list[dict[str, str]] = []
    confidence = "fallback"
    for director in _entry_names(movie.directors):
        bucket = profile["directors"].get(_normalized_key(director))
        if not bucket:
            continue
        examples = [title for title in bucket["titles"] if title != movie.title][:2]
        text = (
            f"Same director as {', '.join(examples)}."
            if examples
            else "Same director as one of your higher-rated library picks."
        )
        signals.append({"type": "director", "text": text})
        confidence = "high"
        break

    if confidence != "high":
        genre_matches = []
        for genre in _entry_names(movie.genres):
            bucket = profile["genres"].get(_normalized_key(genre))
            if bucket:
                genre_matches.append((bucket["count"], genre, bucket))
        if genre_matches:
            _, genre, bucket = max(genre_matches, key=lambda item: item[0])
            examples = [title for title in bucket["titles"] if title != movie.title][:2]
            text = (
                f"Matches your high-rated {genre} pattern around {', '.join(examples)}."
                if examples
                else f"Matches a {genre} pattern in your higher-rated library titles."
            )
            signals.append({"type": "genre", "text": text})
            confidence = "medium"

    source_key = _normalized_key(movie.source)
    if source_key:
        source_count = profile["sources"].get(source_key, 0)
        text = (
            f"Source signal: {movie.source} appears often in your library picks."
            if source_count
            else f"Source signal: {movie.source}."
        )
        signals.append({"type": "source", "text": text})
        if confidence == "fallback":
            confidence = "medium"

    score = float(movie.personal_score or 0)
    if score > 0:
        signals.append({"type": "score", "text": f"Library rating signal: {score:g}."})
        if confidence == "fallback" and score >= 5:
            confidence = "medium"
    if metadata["is_clean"]:
        signals.append(
            {
                "type": "metadata",
                "text": f"Clean metadata ({metadata['score']}/{metadata['maximum']} fields).",
            }
        )
    if not signals:
        signals.append(
            {
                "type": "fallback",
                "text": "Safe fallback from the eligible watch-next pool.",
            }
        )
    return {
        "summary": " ".join(signal["text"] for signal in signals[:2]),
        "detail": signals[2]["text"] if len(signals) > 2 else "",
        "signals": signals[:4],
        "confidence": confidence,
    }


def _recommendation_tier(
    metadata: dict[str, Any],
    *,
    valid_category: bool,
    has_title_noise: bool,
    source_priority: int,
) -> int:
    if metadata["is_clean"] and valid_category and not has_title_noise and source_priority >= 2:
        return 0
    if metadata["score"] >= 4 and valid_category and not has_title_noise:
        return 1
    if metadata["score"] >= 3 and valid_category:
        return 2
    return 3


def _recommendation_score(
    movie: Movie,
    metadata: dict[str, Any],
    *,
    valid_category: bool,
    has_title_noise: bool,
    source_priority: int,
) -> float:
    score = 220 + source_priority * 14 + metadata["score"] * 12
    score += float(movie.personal_score or 0) * 8
    score += 18 if metadata["is_clean"] else 0
    score += 10 if valid_category else 0
    score += 12 if not has_title_noise else 0
    score -= 28 if metadata["is_weak"] else 0
    return score


def parse_movie_filters(values) -> tuple[dict[str, Any], dict[str, str]]:
    filters: dict[str, Any] = {
        "q": values.get("q", ""),
        "status": values.get("status", ""),
        "category": values.get("category", ""),
        "source": values.get("source", ""),
        "genre": values.get("genre", ""),
        "sort": values.get("sort", "recently_updated"),
        "view": values.get("view", "grid"),
        "favorite": values.get("favorite", "") == "1",
    }
    errors: dict[str, str] = {}
    if filters["status"] and filters["status"] not in MOVIE_STATUSES:
        errors["status"] = "Unknown movie status."
    if filters["sort"] not in SORT_VALUES:
        errors["sort"] = "Unknown sort order."
    if filters["view"] not in {"grid", "list"}:
        errors["view"] = "Unknown view."
    for name, cast, minimum, maximum in (
        ("year_min", int, 1800, 2200),
        ("year_max", int, 1800, 2200),
        ("score_min", float, 0, 5),
        ("score_max", float, 0, 5),
    ):
        raw = values.get(name)
        if raw in (None, ""):
            filters[name] = None
            continue
        try:
            parsed = cast(raw)
        except (TypeError, ValueError):
            errors[name] = "Invalid numeric value."
            continue
        if not minimum <= parsed <= maximum:
            errors[name] = f"Must be between {minimum} and {maximum}."
        filters[name] = parsed
    return filters, errors


class MovieService:
    @staticmethod
    def custom_lists(owner_user_id: int) -> list[MovieCustomList]:
        return list(
            db.session.scalars(
                db.select(MovieCustomList)
                .where(MovieCustomList.owner_user_id == owner_user_id)
                .options(
                    selectinload(MovieCustomList.items).selectinload(MovieCustomListItem.movie)
                )
                .order_by(MovieCustomList.updated_at.desc(), MovieCustomList.title.asc())
            )
        )

    @staticmethod
    def create_custom_list(
        owner_user_id: int, *, title: str, description: str = ""
    ) -> MovieCustomList:
        name = " ".join(str(title or "").split())
        if not name:
            raise ValueError("A custom list needs a title.")
        custom_list = MovieCustomList(
            owner_user_id=int(owner_user_id),
            title=name[:160],
            description=str(description or "").strip()[:2000],
        )
        db.session.add(custom_list)
        db.session.commit()
        return custom_list

    @staticmethod
    def custom_list_for_owner(
        owner_user_id: int, custom_list_id: str
    ) -> MovieCustomList | None:
        return db.session.scalar(
            db.select(MovieCustomList)
            .where(
                MovieCustomList.id == custom_list_id,
                MovieCustomList.owner_user_id == owner_user_id,
            )
            .options(
                selectinload(MovieCustomList.items).selectinload(MovieCustomListItem.movie)
            )
        )

    @staticmethod
    def update_custom_list(
        custom_list: MovieCustomList, *, title: str, description: str
    ) -> MovieCustomList:
        name = " ".join(str(title or "").split())
        if not name:
            raise ValueError("A custom list needs a title.")
        custom_list.title = name[:160]
        custom_list.description = str(description or "").strip()[:2000]
        db.session.commit()
        return custom_list

    @staticmethod
    def delete_custom_list(custom_list: MovieCustomList) -> None:
        db.session.delete(custom_list)
        db.session.commit()

    @staticmethod
    def add_to_custom_list(custom_list: MovieCustomList, movie: Movie) -> None:
        existing = db.session.get(MovieCustomListItem, (custom_list.id, movie.id))
        if existing is not None:
            return
        position = int(
            db.session.scalar(
                db.select(func.coalesce(func.max(MovieCustomListItem.position), -1)).where(
                    MovieCustomListItem.custom_list_id == custom_list.id
                )
            )
            or -1
        ) + 1
        db.session.add(
            MovieCustomListItem(
                custom_list_id=custom_list.id, movie_id=movie.id, position=position
            )
        )
        HistoryService.record(
            domain="movies",
            entity_type="movie_list",
            entity_id=custom_list.id,
            event_type="list_membership_added",
            label=f"Added {movie.title} to {custom_list.title}",
            metadata={"media_key": movie.media_key, "list_id": custom_list.id},
        )
        db.session.commit()

    @staticmethod
    def remove_from_custom_list(custom_list: MovieCustomList, movie_id: str) -> bool:
        item = db.session.get(MovieCustomListItem, (custom_list.id, movie_id))
        if item is None:
            return False
        db.session.delete(item)
        db.session.commit()
        return True

    @staticmethod
    def ensure_library_entry(movie: Movie) -> MovieLibraryEntry:
        """Create V2 personal state without discarding legacy Movie fields."""

        if not movie.id or not movie.media_key:
            db.session.flush()
        if movie.library_entry:
            return movie.library_entry
        entry = db.session.get(MovieLibraryEntry, movie.media_key)
        if entry is None:
            label = str(dict(movie.metadata_state or {}).get("personal_score_label") or "").strip()
            entry = MovieLibraryEntry(
                media_key=movie.media_key,
                movie_id=movie.id,
                lifecycle_status=lifecycle_status_for(movie.status),
                is_favorite=False,
                personal_rating=movie.personal_score,
                personal_label=label,
                added_at=movie.created_at or utc_now(),
            )
            db.session.add(entry)
        return entry

    @staticmethod
    def assign_canonical_identity(
        movie: Movie,
        *,
        allow_tmdb_reconciliation: bool = False,
    ) -> str:
        """Assign a key for a new title; never silently rebind personal state."""

        if not movie.id:
            db.session.flush()
        candidate = canonical_media_key(
            movie_id=movie.id,
            media_type=movie.media_type,
            external_ids=movie.external_ids,
        )
        if not movie.media_key or allow_tmdb_reconciliation:
            movie.media_key = candidate
        return movie.media_key

    @staticmethod
    def set_status(movie: Movie, status: str) -> Movie:
        if status not in MOVIE_STATUSES:
            raise ValueError("Unknown movie status.")
        previous_status = effective_lifecycle_status(movie)
        movie.status = status
        entry = MovieService.ensure_library_entry(movie)
        now = utc_now()
        entry.lifecycle_status = lifecycle_status_for(status)
        entry.manual_lifecycle_at = now
        if entry.lifecycle_status == "watched":
            entry.completed_at = entry.completed_at or now
            entry.last_watched_at = entry.last_watched_at or now
        elif status in {"want_to_watch", "unknown"}:
            entry.completed_at = None
        if entry.lifecycle_status != previous_status:
            is_completion = entry.lifecycle_status == "watched"
            HistoryService.record(
                domain="movies",
                entity_type="movie",
                entity_id=movie.id,
                event_type="movie_completed" if is_completion else "lifecycle_changed",
                label=(
                    f"Completed {movie.title}"
                    if is_completion
                    else f"{movie.title}: {entry.lifecycle_status.replace('_', ' ')}"
                ),
                metadata={"media_key": movie.media_key, "lifecycle_status": entry.lifecycle_status},
            )
        db.session.commit()
        return movie

    @staticmethod
    def set_score(movie: Movie, score: float | None, *, label: str | None = None) -> Movie:
        if score is not None and not 0 <= score <= 5:
            raise ValueError("Score must be between 0 and 5.")
        entry = MovieService.ensure_library_entry(movie)
        previous_score = entry.personal_rating
        previous_label = entry.personal_label
        movie.personal_score = score
        entry.personal_rating = score
        if label is not None or score is None:
            metadata_state = dict(movie.metadata_state or {})
            if label:
                metadata_state["personal_score_label"] = label
            else:
                metadata_state.pop("personal_score_label", None)
            movie.metadata_state = metadata_state
            entry.personal_label = label or ""
        if entry.personal_rating != previous_score or entry.personal_label != previous_label:
            HistoryService.record(
                domain="movies",
                entity_type="movie",
                entity_id=movie.id,
                event_type="rating",
                label=f"Rated {movie.title}: {score if score is not None else 'cleared'}",
                metadata={"media_key": movie.media_key, "rating": score, "label": entry.personal_label},
            )
        db.session.commit()
        return movie

    @staticmethod
    def set_favorite(movie: Movie, is_favorite: bool) -> Movie:
        entry = MovieService.ensure_library_entry(movie)
        previous_favorite = entry.is_favorite
        entry.is_favorite = bool(is_favorite)
        if entry.is_favorite != previous_favorite:
            HistoryService.record(
                domain="movies",
                entity_type="movie",
                entity_id=movie.id,
                event_type="favorite",
                label=("Favorited " if entry.is_favorite else "Removed favorite ") + movie.title,
                metadata={"media_key": movie.media_key, "is_favorite": entry.is_favorite},
            )
        db.session.commit()
        return movie

    @staticmethod
    def save_progress(
        movie: Movie,
        *,
        current_seconds: int,
        duration_seconds: int,
        completed: bool,
        ended: bool = False,
        client_updated_at: datetime | None = None,
        season: int | None = None,
        episode: int | None = None,
    ) -> MovieProgress:
        season, episode = MovieService.progress_scope(season=season, episode=episode)
        if current_seconds < 0 or duration_seconds < 0:
            raise ValueError("Progress values must be non-negative.")
        if duration_seconds and current_seconds > duration_seconds:
            current_seconds = duration_seconds
        progress = MovieService.get_progress(movie, season=season, episode=episode)
        if progress is None:
            progress = MovieProgress(movie=movie, season=season, episode=episode)
        if progress.id and client_updated_at and progress.client_updated_at:
            stored = progress.client_updated_at
            if stored.tzinfo is None:
                stored = stored.replace(tzinfo=UTC)
            candidate = client_updated_at
            if candidate.tzinfo is None:
                candidate = candidate.replace(tzinfo=UTC)
            if candidate < stored:
                raise ProgressConflictError(progress_dict(progress) or {})
        was_completed = bool(progress.completed)
        progress.current_seconds = current_seconds
        progress.duration_seconds = duration_seconds
        progress.completed = progress_is_completed(
            current_seconds=current_seconds,
            duration_seconds=duration_seconds,
            ended=bool(completed or ended),
            season=season,
            episode=episode,
        )
        progress.client_updated_at = client_updated_at or utc_now()
        db.session.add(progress)
        entry = MovieService.ensure_library_entry(movie)
        entry.last_watched_at = progress.client_updated_at
        manual_transition_is_newer = bool(
            entry.manual_lifecycle_at
            and progress.client_updated_at < entry.manual_lifecycle_at
        )
        if not manual_transition_is_newer:
            if season is None:
                if progress.completed:
                    entry.lifecycle_status = "watched"
                    entry.completed_at = entry.completed_at or progress.client_updated_at
                    movie.status = "watched"
                elif entry.lifecycle_status == "want_to_watch":
                    entry.lifecycle_status = "watching"
                    movie.status = "watching"
            elif not progress.completed and entry.lifecycle_status == "want_to_watch":
                entry.lifecycle_status = "watching"
                movie.status = "watching"
        if progress.completed and not was_completed:
            episode_scope = season is not None and episode is not None
            HistoryService.record(
                domain="movies",
                entity_type="episode" if episode_scope else "movie",
                entity_id=movie.id,
                event_type="episode_completed" if episode_scope else "movie_completed",
                label=(
                    f"Completed {movie.title} S{season:02d}E{episode:02d}"
                    if episode_scope
                    else f"Completed {movie.title}"
                ),
                metadata={
                    "media_key": movie.media_key,
                    "season": season,
                    "episode": episode,
                    "duration_seconds": duration_seconds,
                },
            )
        db.session.commit()
        return progress

    @staticmethod
    def progress_scope(
        *,
        season: int | None = None,
        episode: int | None = None,
    ) -> tuple[int | None, int | None]:
        if season is None and episode is None:
            return None, None
        if season is None or episode is None:
            raise ValueError("Choose a season and episode for episode progress.")
        if season < 0 or episode < 1:
            raise ValueError("Choose a valid season and episode for episode progress.")
        return int(season), int(episode)

    @staticmethod
    def get_progress(
        movie: Movie,
        *,
        season: int | None = None,
        episode: int | None = None,
    ) -> MovieProgress | None:
        season, episode = MovieService.progress_scope(season=season, episode=episode)
        query = db.select(MovieProgress).where(MovieProgress.movie_id == movie.id)
        if season is None:
            query = query.where(MovieProgress.season.is_(None), MovieProgress.episode.is_(None))
        else:
            query = query.where(MovieProgress.season == season, MovieProgress.episode == episode)
        return db.session.scalar(query.order_by(MovieProgress.updated_at.desc()).limit(1))

    @staticmethod
    def continue_watching(limit: int = 6) -> list[Movie]:
        lifecycle_status = lifecycle_status_sql()
        query = (
            db.select(Movie)
            .join(MovieProgress)
            .outerjoin(MovieLibraryEntry, MovieLibraryEntry.movie_id == Movie.id)
            .where(
                MovieProgress.completed.is_(False),
                MovieProgress.current_seconds > 0,
                lifecycle_status != "watched",
            )
            .options(
                selectinload(Movie.library_entry),
                selectinload(Movie.progress),
                selectinload(Movie.progress_entries),
            )
            .distinct()
            .order_by(MovieProgress.updated_at.desc())
            .limit(limit)
        )
        return list(db.session.scalars(query))

    @staticmethod
    def watching_now() -> Movie | None:
        lifecycle_status = lifecycle_status_sql()
        active_progress = db.session.scalar(
            db.select(Movie)
            .join(MovieProgress)
            .outerjoin(MovieLibraryEntry, MovieLibraryEntry.movie_id == Movie.id)
            .where(
                MovieProgress.completed.is_(False),
                MovieProgress.current_seconds > 0,
                lifecycle_status != "watched",
            )
            .options(
                selectinload(Movie.library_entry),
                selectinload(Movie.progress),
                selectinload(Movie.progress_entries),
            )
            .order_by(MovieProgress.updated_at.desc())
            .limit(1)
        )
        if active_progress is not None:
            return active_progress
        return db.session.scalar(
            db.select(Movie)
            .outerjoin(MovieLibraryEntry, MovieLibraryEntry.movie_id == Movie.id)
            .where(lifecycle_status == "watching")
            .options(selectinload(Movie.library_entry), selectinload(Movie.progress))
            .order_by(Movie.updated_at.desc())
            .limit(1)
        )

    @staticmethod
    def recommended() -> dict[str, Any] | None:
        lifecycle_status = lifecycle_status_sql()
        movie = db.session.scalar(
            db.select(Movie)
            .outerjoin(MovieLibraryEntry, MovieLibraryEntry.movie_id == Movie.id)
            .where(lifecycle_status == "want_to_watch")
            .options(selectinload(Movie.library_entry))
            .order_by(
                case(
                    (
                        MovieLibraryEntry.personal_rating.is_not(None),
                        MovieLibraryEntry.personal_rating,
                    ),
                    else_=Movie.personal_score,
                ).desc().nullslast(),
                Movie.updated_at.desc(),
            )
            .limit(1)
        )
        return movie_item(movie) if movie else None

    @staticmethod
    def rotating_recommended(position: int) -> dict[str, Any] | None:
        curated = MovieService.recommendation_pool()["items"]
        if curated:
            return curated[position % len(curated)]
        movies = list(
            db.session.scalars(
                db.select(Movie)
                .outerjoin(MovieLibraryEntry, MovieLibraryEntry.movie_id == Movie.id)
                .where(lifecycle_status_sql() == "want_to_watch")
                .options(selectinload(Movie.library_entry))
                .order_by(Movie.personal_score.desc().nullslast(), Movie.updated_at.desc())
            )
        )
        return movie_item(movies[position % len(movies)]) if movies else None

    @staticmethod
    def what_should_i_watch(
        *,
        media_type: str = "",
        genre: str = "",
        runtime_max: int | None = None,
        language: str = "",
        decade: int | None = None,
        sort: str = "random",
    ) -> dict[str, Any] | None:
        """Select only an unwatched personal title with factual local filters."""

        entries = list(
            db.session.scalars(
                db.select(MovieLibraryEntry)
                .join(Movie, MovieLibraryEntry.movie_id == Movie.id)
                .where(MovieLibraryEntry.lifecycle_status != "watched")
                .options(selectinload(MovieLibraryEntry.movie))
                .order_by(MovieLibraryEntry.media_key)
            )
        )
        normalized_type = str(media_type or "").strip().lower()
        normalized_genre = _normalized_key(genre)
        normalized_language = str(language or "").strip().lower()
        normalized_sort = str(sort or "random").strip().lower()
        if normalized_type not in {"", "movie", "tv"}:
            raise ValueError("Type must be movie or tv.")
        if normalized_sort not in WHAT_TO_WATCH_SORTS:
            raise ValueError("Choose a supported What Should I Watch sort.")
        if runtime_max is not None and not 1 <= int(runtime_max) <= 1_000:
            raise ValueError("Maximum runtime must be between 1 and 1000 minutes.")
        if decade is not None and not 1800 <= int(decade) <= 2200:
            raise ValueError("Decade must be between 1800 and 2200.")

        candidates: list[MovieLibraryEntry] = []
        for entry in entries:
            movie = entry.movie
            if movie is None:
                continue
            if normalized_type and movie.media_type != normalized_type:
                continue
            if normalized_genre and normalized_genre not in {
                _normalized_key(name) for name in _entry_names(movie.genres)
            }:
                continue
            if runtime_max is not None and (
                movie.runtime_minutes is None or movie.runtime_minutes > int(runtime_max)
            ):
                continue
            detail = dict(movie.metadata_state or {}).get("tmdb_detail") or {}
            if (
                normalized_language
                and str(detail.get("original_language") or "").lower()
                != normalized_language
            ):
                continue
            if decade is not None and (
                movie.year is None or not int(decade) <= movie.year < int(decade) + 10
            ):
                continue
            candidates.append(entry)
        if not candidates:
            return None
        if normalized_sort == "oldest_added":
            selected_entry = min(candidates, key=lambda entry: (entry.added_at, entry.media_key))
        elif normalized_sort == "recently_added":
            selected_entry = max(candidates, key=lambda entry: (entry.added_at, entry.media_key))
        else:
            selected_entry = SystemRandom().choice(candidates)
        selected = selected_entry.movie
        filters = []
        if normalized_type:
            filters.append(normalized_type)
        if normalized_genre:
            filters.append(f"{genre.strip()} genre")
        if runtime_max is not None:
            filters.append(f"up to {int(runtime_max)} min")
        if normalized_language:
            filters.append(f"{normalized_language.upper()} original language")
        if decade is not None:
            filters.append(f"{int(decade)}s")
        reason = "From your personal unwatched library."
        if filters:
            reason = f"Unwatched in your personal library; matches {', '.join(filters)}."
        return {
            **movie_item(selected),
            "eligibility_reason": reason,
            "eligibility_filters": {
                "media_type": normalized_type,
                "genre": genre.strip(),
                "runtime_max": runtime_max,
                "language": normalized_language,
                "decade": decade,
                "sort": normalized_sort,
            },
        }

    @staticmethod
    def because_you_watched(
        *, limit: int = 12, anchor_id: int | str | None = None
    ) -> dict[str, Any] | None:
        """Project cached TMDB similar/recommendation cards from personal anchors.

        This is intentionally a cache-only discovery rail. It never refreshes an
        anchor, inserts a Movie, or returns an item that already exists in the
        local library.
        """

        movies = list(
            db.session.scalars(
                db.select(Movie).options(selectinload(Movie.library_entry))
            )
        )
        local_keys = {movie.media_key for movie in movies}
        anchors = [
            movie
            for movie in movies
            if effective_lifecycle_status(movie) == "watched"
            or bool(movie.library_entry and movie.library_entry.is_favorite)
            or (effective_personal_rating(movie) or 0) >= 4
        ]
        anchors.sort(
            key=lambda movie: (
                bool(movie.library_entry and movie.library_entry.is_favorite),
                float(effective_personal_rating(movie) or 0),
                _utc_sort_key(
                    movie.library_entry.last_watched_at
                    or movie.library_entry.updated_at
                    if movie.library_entry
                    else movie.updated_at
                ),
                movie.id,
            ),
            reverse=True,
        )
        if anchor_id not in (None, ""):
            try:
                requested_id = int(anchor_id)
            except (TypeError, ValueError):
                requested_id = None
            requested = next((movie for movie in anchors if movie.id == requested_id), None)
            if requested is not None:
                anchors = [requested] + [movie for movie in anchors if movie.id != requested.id]
        anchor_options = [movie_item(movie) for movie in anchors[:24]]
        for anchor in anchors:
            detail = dict(anchor.metadata_state or {}).get("tmdb_detail") or {}
            candidates: list[dict[str, Any]] = []
            seen: set[str] = set()
            for signal, related in (
                ("TMDB recommendation", detail.get("recommendations") or []),
                ("Similar on TMDB", detail.get("similar") or []),
            ):
                for item in related:
                    try:
                        tmdb_id = int(item.get("tmdb_id"))
                    except (AttributeError, TypeError, ValueError):
                        continue
                    media_type = str(item.get("media_type") or anchor.media_type).lower()
                    if media_type not in {"movie", "tv"}:
                        continue
                    media_key = f"{media_type}:{tmdb_id}"
                    if media_key in local_keys or media_key in seen:
                        continue
                    seen.add(media_key)
                    candidates.append(
                        {
                            "media_key": media_key,
                            "tmdb_id": tmdb_id,
                            "media_type": media_type,
                            "title": str(item.get("title") or "Untitled"),
                            "year": _optional_int(item.get("year")),
                            "poster_url": str(item.get("poster_url") or ""),
                            "rating": item.get("rating"),
                            "signal": signal,
                            "detail_url": f"/movies/discover/{media_type}/{tmdb_id}",
                        }
                    )
                    if len(candidates) >= max(1, min(limit, 24)):
                        break
                if len(candidates) >= max(1, min(limit, 24)):
                    break
            if candidates:
                return {
                    "anchor": movie_item(anchor),
                    "anchors": anchor_options,
                    "items": candidates,
                    "cache_only": True,
                }
        return None

    @staticmethod
    def recommendation_pool(*, category: str = "", source: str = "") -> dict[str, Any]:
        movies = list(db.session.scalars(db.select(Movie)))
        profile = _recommendation_profile(movies)
        category_key = _normalized_key(category)
        source_key = _normalized_key(source)
        candidates: list[dict[str, Any]] = []
        excluded_watched = 0
        excluded_filters = 0
        excluded_weak = 0

        for movie in movies:
            lifecycle_status = effective_lifecycle_status(movie)
            if lifecycle_status == "watched":
                excluded_watched += 1
                continue
            if lifecycle_status != "want_to_watch":
                continue
            if category_key and _normalized_key(movie.category) != category_key:
                excluded_filters += 1
                continue
            if source_key and _normalized_key(movie.source) != source_key:
                excluded_filters += 1
                continue

            metadata = _metadata_quality(movie)
            valid_category = _normalized_key(movie.category) in VALID_MOVIE_CATEGORIES
            has_title_noise = _title_has_noise(movie.title)
            source_priority = _source_priority(movie.source)
            tier = _recommendation_tier(
                metadata,
                valid_category=valid_category,
                has_title_noise=has_title_noise,
                source_priority=source_priority,
            )
            if tier > 2:
                excluded_weak += 1
                continue
            explanation = _recommendation_explanation(movie, profile, metadata)
            candidates.append(
                {
                    **movie_item(movie),
                    "category": movie.category,
                    "source": movie.source,
                    "overview": movie.overview,
                    "genres": _entry_names(movie.genres),
                    "directors": _entry_names(movie.directors),
                    "pool": "primary",
                    "tier": tier,
                    "curation_score": _recommendation_score(
                        movie,
                        metadata,
                        valid_category=valid_category,
                        has_title_noise=has_title_noise,
                        source_priority=source_priority,
                    ),
                    "metadata_quality": metadata,
                    "recommendation_explanation": explanation,
                    "recommendation_reason": explanation["summary"],
                }
            )

        candidates.sort(
            key=lambda item: (
                item["tier"],
                -float(item["curation_score"]),
                -float(item["personal_score"] or 0),
                -int(item["metadata_quality"]["score"]),
                item["title"].casefold(),
            )
        )
        for rank, item in enumerate(candidates, start=1):
            item["rank"] = rank
        return {
            "items": candidates,
            "summary": {
                "total_titles": len(movies),
                "eligible": len(candidates),
                "excluded_watched": excluded_watched,
                "excluded_filters": excluded_filters,
                "excluded_weak": excluded_weak,
                "liked_titles": profile["liked_count"],
                "strong_titles": profile["strong_count"],
            },
            "filters": {"category": category, "source": source},
        }
