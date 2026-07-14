from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import selectinload

from app.extensions import db
from app.history.services import HistoryService
from app.movies.models import Movie, MovieProgress
from app.shared.time import utc_now

MOVIE_STATUSES = {"want_to_watch", "watching", "finished", "watched", "unknown"}
SORT_VALUES = {"title_asc", "title_desc", "score_desc", "year_desc", "recently_updated"}


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
