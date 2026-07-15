from __future__ import annotations

from datetime import UTC, datetime

from app.books.services import BookService
from app.chess.services import ChessService
from app.movies.services import MovieService, movie_item
from app.reading.services import ReadingService
from app.shared.freshness import list_freshness
from app.youtube.services import YouTubeService

MOVIE_ROTATION_SECONDS = 60 * 60
YOUTUBE_ROTATION_SECONDS = 5 * 60
YOUTUBE_ROTATION_SIZE = 4


def _rotation_bucket(moment: datetime, interval: int) -> int:
    return int(moment.timestamp()) // interval


def _next_rotation(bucket: int, interval: int) -> str:
    value = datetime.fromtimestamp((bucket + 1) * interval, tz=UTC)
    return value.isoformat().replace("+00:00", "Z")


def _cyclic_window(items: list[dict], *, start: int, limit: int) -> list[dict]:
    if not items:
        return []
    return [items[(start + index) % len(items)] for index in range(min(limit, len(items)))]


class TodayService:
    @staticmethod
    def live_rotation(at: datetime | None = None) -> dict:
        moment = at or datetime.now(UTC)
        moment = (
            moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
        )
        movie_bucket = _rotation_bucket(moment, MOVIE_ROTATION_SECONDS)
        youtube_bucket = _rotation_bucket(moment, YOUTUBE_ROTATION_SECONDS)
        youtube_feed = YouTubeService.feed(
            source="watch_later",
            order="shuffle",
            limit=5000,
            seed=f"today:{moment.date().isoformat()}",
        )
        youtube_items = youtube_feed["items"]
        youtube_start = (youtube_bucket * YOUTUBE_ROTATION_SIZE) % max(
            len(youtube_items), 1
        )
        return {
            "recommended_movie": MovieService.rotating_recommended(movie_bucket),
            "latest_youtube": _cyclic_window(
                youtube_items,
                start=youtube_start,
                limit=YOUTUBE_ROTATION_SIZE,
            ),
            "rotation": {
                "movie_bucket": movie_bucket,
                "youtube_bucket": youtube_bucket,
                "movie_interval_seconds": MOVIE_ROTATION_SECONDS,
                "youtube_interval_seconds": YOUTUBE_ROTATION_SECONDS,
                "movie_next_at": _next_rotation(movie_bucket, MOVIE_ROTATION_SECONDS),
                "youtube_next_at": _next_rotation(youtube_bucket, YOUTUBE_ROTATION_SECONDS),
            },
        }

    @staticmethod
    def workspace(at: datetime | None = None) -> dict:
        warnings = [item for item in list_freshness() if item["state"] != "fresh"]
        live = TodayService.live_rotation(at)
        return {
            "continue_watching": [movie_item(movie) for movie in MovieService.continue_watching(4)],
            **live,
            "continue_reading": ReadingService.continue_reading(4),
            "article_of_day": ReadingService.article_of_day(),
            "current_book": BookService.current_book(),
            "chess_training": ChessService.dashboard()["puzzles"][:3],
            "freshness_warnings": warnings,
        }
