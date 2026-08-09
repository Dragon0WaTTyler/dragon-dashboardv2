from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import selectinload

from app.extensions import db
from app.history.services import HistoryService
from app.movies.models import Movie, MovieProgress
from app.movies.scoring import score_option_for_input
from app.playback.models import PlaybackSource
from app.shared.time import utc_now

MOVIE_STATUSES = {"want_to_watch", "watching", "finished", "watched", "unknown"}
SORT_VALUES = {"title_asc", "title_desc", "score_desc", "year_desc", "recently_updated"}
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
    percent = 0
    if progress.duration_seconds > 0:
        percent = min(100, round(progress.current_seconds / progress.duration_seconds * 100))
    completed = bool(progress.completed or percent >= 92)
    episode = int(progress.episode) + 1 if completed else int(progress.episode)
    return {
        "season": int(progress.season),
        "episode": episode,
        "from_completed_episode": completed,
    }


def movie_item(movie: Movie) -> dict[str, Any]:
    progress = _display_progress(movie)
    score_option = score_option_for_input(
        movie.personal_score,
        stored_label=dict(movie.metadata_state or {}).get("personal_score_label"),
    )
    return {
        "id": movie.id,
        "title": movie.title,
        "media_type": movie.media_type,
        "year": movie.year,
        "runtime_minutes": movie.runtime_minutes,
        "status": movie.status,
        "personal_score": movie.personal_score,
        "personal_score_label": score_option.label if score_option else None,
        "poster_url": movie.poster_url,
        "progress": progress_dict(progress),
        "watch_target": _watch_target(progress),
    }


def movie_detail(movie: Movie) -> dict[str, Any]:
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
        "metadata_state": dict(movie.metadata_state or {}),
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
        if progress.season and progress.episode:
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
    seasons: list[dict[str, Any]] = []

    for season in catalog["seasons"]:
        season_number = int(season.get("season_number") or 0)
        if season_number < 1:
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
                watched_episodes += 1
            if source_lookup.get((season_number, episode_number), {}).get("exact") or source_lookup.get((season_number, episode_number), {}).get("fallback"):
                available_count += 1
        episode_count = max(len([row for row in episode_rows if int(row.get("episode_number") or 0) > 0]), int(season.get("episode_count") or 0))
        if episode_count and completed_count >= episode_count:
            completed_seasons += 1
        seasons.append(
            {
                **season,
                "season_number": season_number,
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
    next_episode = None
    if selected_episode:
        next_episode = next(
            (item for item in episodes if int(item["episode_number"]) > int(selected_episode)),
            None,
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
    def set_status(movie: Movie, status: str) -> Movie:
        if status not in MOVIE_STATUSES:
            raise ValueError("Unknown movie status.")
        movie.status = status
        HistoryService.record(
            domain="movies",
            entity_type="movie",
            entity_id=movie.id,
            event_type="status",
            label=f"{movie.title}: {status.replace('_', ' ')}",
        )
        db.session.commit()
        return movie

    @staticmethod
    def set_score(movie: Movie, score: float | None, *, label: str | None = None) -> Movie:
        if score is not None and not 0 <= score <= 5:
            raise ValueError("Score must be between 0 and 5.")
        movie.personal_score = score
        if label is not None or score is None:
            metadata_state = dict(movie.metadata_state or {})
            if label:
                metadata_state["personal_score_label"] = label
            else:
                metadata_state.pop("personal_score_label", None)
            movie.metadata_state = metadata_state
        HistoryService.record(
            domain="movies",
            entity_type="movie",
            entity_id=movie.id,
            event_type="rating",
            label=f"Rated {movie.title}: {score if score is not None else 'cleared'}",
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
        progress.current_seconds = current_seconds
        progress.duration_seconds = duration_seconds
        progress.completed = completed
        progress.client_updated_at = client_updated_at or utc_now()
        db.session.add(progress)
        HistoryService.record(
            domain="movies",
            entity_type="movie",
            entity_id=movie.id,
            event_type="playback_progress",
            label=(
                f"Playback progress saved for {movie.title}"
                if not season or not episode
                else f"Playback progress saved for {movie.title} S{season:02d}E{episode:02d}"
            ),
            metadata={
                "current_seconds": current_seconds,
                "duration_seconds": duration_seconds,
                "season": season,
                "episode": episode,
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
        if not season or not episode:
            raise ValueError("Choose a season and episode for episode progress.")
        if season < 1 or episode < 1:
            raise ValueError("Season and episode must be positive.")
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
        query = (
            db.select(Movie)
            .join(MovieProgress)
            .where(MovieProgress.completed.is_(False), MovieProgress.current_seconds > 0)
            .options(selectinload(Movie.progress), selectinload(Movie.progress_entries))
            .distinct()
            .order_by(MovieProgress.updated_at.desc())
            .limit(limit)
        )
        return list(db.session.scalars(query))

    @staticmethod
    def watching_now() -> Movie | None:
        active_progress = db.session.scalar(
            db.select(Movie)
            .join(MovieProgress)
            .where(MovieProgress.completed.is_(False), MovieProgress.current_seconds > 0)
            .options(selectinload(Movie.progress), selectinload(Movie.progress_entries))
            .order_by(MovieProgress.updated_at.desc())
            .limit(1)
        )
        if active_progress is not None:
            return active_progress
        return db.session.scalar(
            db.select(Movie)
            .where(Movie.status == "watching")
            .options(selectinload(Movie.progress))
            .order_by(Movie.updated_at.desc())
            .limit(1)
        )

    @staticmethod
    def recommended() -> dict[str, Any] | None:
        movie = db.session.scalar(
            db.select(Movie)
            .where(Movie.status == "want_to_watch")
            .order_by(Movie.personal_score.desc().nullslast(), Movie.updated_at.desc())
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
                .where(Movie.status == "want_to_watch")
                .order_by(Movie.personal_score.desc().nullslast(), Movie.updated_at.desc())
            )
        )
        return movie_item(movies[position % len(movies)]) if movies else None

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
            if movie.status in {"finished", "watched"}:
                excluded_watched += 1
                continue
            if movie.status != "want_to_watch":
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
