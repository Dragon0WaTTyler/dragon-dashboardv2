from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import selectinload

from app.extensions import db
from app.history.services import HistoryService
from app.movies.models import Movie, MovieProgress
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
        "current_seconds": progress.current_seconds,
        "duration_seconds": progress.duration_seconds,
        "percent": percent,
        "completed": progress.completed,
        "updated_at": _utc_json(progress.updated_at),
    }


def movie_item(movie: Movie) -> dict[str, Any]:
    return {
        "id": movie.id,
        "title": movie.title,
        "media_type": movie.media_type,
        "year": movie.year,
        "status": movie.status,
        "personal_score": movie.personal_score,
        "poster_url": movie.poster_url,
        "progress": progress_dict(movie.progress),
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
    def set_score(movie: Movie, score: float | None) -> Movie:
        if score is not None and not 0 <= score <= 5:
            raise ValueError("Score must be between 0 and 5.")
        movie.personal_score = score
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
    ) -> MovieProgress:
        if current_seconds < 0 or duration_seconds < 0:
            raise ValueError("Progress values must be non-negative.")
        if duration_seconds and current_seconds > duration_seconds:
            current_seconds = duration_seconds
        progress = movie.progress or MovieProgress(movie=movie)
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
            label=f"Playback progress saved for {movie.title}",
            metadata={"current_seconds": current_seconds, "duration_seconds": duration_seconds},
        )
        db.session.commit()
        return progress

    @staticmethod
    def continue_watching(limit: int = 6) -> list[Movie]:
        query = (
            db.select(Movie)
            .join(MovieProgress)
            .where(MovieProgress.completed.is_(False), MovieProgress.current_seconds > 0)
            .options(selectinload(Movie.progress))
            .order_by(MovieProgress.updated_at.desc())
            .limit(limit)
        )
        return list(db.session.scalars(query))

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
