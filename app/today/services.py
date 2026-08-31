from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.books.services import BookService
from app.chess.services import ChessService
from app.movies.services import MovieService, movie_item
from app.reading.services import ReadingService
from app.shared.freshness import list_freshness
from app.youtube.services import YouTubeService

MOVIE_ROTATION_SECONDS = 60 * 60
YOUTUBE_ROTATION_SECONDS = 5 * 60
YOUTUBE_ROTATION_SIZE = 4
READING_ROTATION_SECONDS = 5 * 60
READING_ROTATION_SIZE = 4
READING_MIX_POOL_SIZE = 24
POCKETTUBE_FAVORITE_GROUP = "my favoret"


def _rotation_bucket(moment: datetime, interval: int) -> int:
    return int(moment.timestamp()) // interval


def _next_rotation(bucket: int, interval: int) -> str:
    value = datetime.fromtimestamp((bucket + 1) * interval, tz=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _cyclic_window(items: list[dict], *, start: int, limit: int) -> list[dict]:
    if not items:
        return []
    return [items[(start + index) % len(items)] for index in range(min(limit, len(items)))]


def _seeded_random_window(items: list[dict], *, seed: str, limit: int) -> list[dict]:
    if not items:
        return []
    return sorted(
        items,
        key=lambda item: hashlib.sha256(
            f"{seed}:{item.get('id') or item.get('title') or ''}".encode()
        ).hexdigest(),
    )[:limit]


class TodayService:
    @staticmethod
    def live_rotation(at: datetime | None = None) -> dict:
        moment = at or datetime.now(timezone.utc)
        moment = (
            moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)
        )
        movie_bucket = _rotation_bucket(moment, MOVIE_ROTATION_SECONDS)
        youtube_bucket = _rotation_bucket(moment, YOUTUBE_ROTATION_SECONDS)
        reading_bucket = _rotation_bucket(moment, READING_ROTATION_SECONDS)
        youtube_items = YouTubeService.rotation_window(
            source="watch_later",
            seed=f"today:{moment.date().isoformat()}",
            limit=YOUTUBE_ROTATION_SIZE,
            offset=youtube_bucket * YOUTUBE_ROTATION_SIZE,
        )
        pockettube_favorite_group = YouTubeService.rotation_window(
            source="pockettube",
            group=POCKETTUBE_FAVORITE_GROUP,
            seed=f"today:pockettube:{moment.date().isoformat()}",
            limit=YOUTUBE_ROTATION_SIZE,
            offset=youtube_bucket * YOUTUBE_ROTATION_SIZE,
        )
        reading_items = ReadingService.latest_news_mix(limit=READING_MIX_POOL_SIZE)
        news_mix = _seeded_random_window(
            reading_items,
            seed=f"today:reading:{reading_bucket}",
            limit=READING_ROTATION_SIZE,
        )
        return {
            "recommended_movie": MovieService.rotating_recommended(movie_bucket),
            "latest_youtube": youtube_items,
            "pockettube_favorite": pockettube_favorite_group,
            "news_mix": news_mix,
            "continue_reading": news_mix,
            "rotation": {
                "movie_bucket": movie_bucket,
                "youtube_bucket": youtube_bucket,
                "reading_bucket": reading_bucket,
                "movie_interval_seconds": MOVIE_ROTATION_SECONDS,
                "youtube_interval_seconds": YOUTUBE_ROTATION_SECONDS,
                "reading_interval_seconds": READING_ROTATION_SECONDS,
                "movie_next_at": _next_rotation(movie_bucket, MOVIE_ROTATION_SECONDS),
                "youtube_next_at": _next_rotation(youtube_bucket, YOUTUBE_ROTATION_SECONDS),
                "reading_next_at": _next_rotation(reading_bucket, READING_ROTATION_SECONDS),
            },
        }

    @staticmethod
    def workspace(at: datetime | None = None) -> dict:
        warnings = [item for item in list_freshness() if item["state"] != "fresh"]
        live = TodayService.live_rotation(at)
        watching_now = MovieService.watching_now()
        current_books = BookService.current_books()
        return {
            "continue_watching": [],
            "watching_now": movie_item(watching_now) if watching_now else None,
            **live,
            "article_of_day": ReadingService.article_of_day(),
            "current_book": current_books[0] if current_books else None,
            "current_books": current_books,
            "chess_training": ChessService.dashboard()["puzzles"][:3],
            "freshness_warnings": warnings,
        }
