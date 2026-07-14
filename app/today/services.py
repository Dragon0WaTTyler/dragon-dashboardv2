from __future__ import annotations

from app.books.services import BookService
from app.chess.services import ChessService
from app.movies.services import MovieService, movie_item
from app.reading.services import ReadingService
from app.shared.freshness import list_freshness
from app.youtube.services import YouTubeService


class TodayService:
    @staticmethod
    def workspace() -> dict:
        warnings = [item for item in list_freshness() if item["state"] != "fresh"]
        return {
            "continue_watching": [movie_item(movie) for movie in MovieService.continue_watching(4)],
            "recommended_movie": MovieService.recommended(),
            "latest_youtube": YouTubeService.latest_watch_later(4),
            "continue_reading": ReadingService.continue_reading(4),
            "article_of_day": ReadingService.article_of_day(),
            "current_book": BookService.current_book(),
            "chess_training": ChessService.dashboard()["puzzles"][:3],
            "freshness_warnings": warnings,
        }
