from __future__ import annotations

from datetime import timedelta

from app.chess.models import ChessGame, ChessPuzzle, PuzzleAttempt
from app.chess.repositories import ChessRepository
from app.extensions import db
from app.history.services import HistoryService
from app.shared.time import utc_now


def game_item(game: ChessGame) -> dict:
    return {
        "id": game.id,
        "external_id": game.external_id,
        "source": game.source,
        "white": game.white,
        "black": game.black,
        "user_color": game.user_color,
        "user_result": game.user_result,
        "result": game.result,
        "played_at": game.played_at.isoformat() if game.played_at else None,
        "time_class": game.time_class,
        "opening": game.opening,
    }


def game_detail(game: ChessGame) -> dict:
    return {
        **game_item(game),
        "time_control": game.time_control,
        "pgn": game.pgn,
        "moves": game.moves,
        "source_url": game.source_url,
        "rated": game.rated,
    }


def puzzle_item(puzzle: ChessPuzzle) -> dict:
    latest = max(puzzle.attempts, key=lambda item: item.started_at, default=None)
    return {
        "id": puzzle.id,
        "external_id": puzzle.external_id,
        "source": puzzle.source,
        "fen": puzzle.fen,
        "moves": puzzle.moves,
        "rating": puzzle.rating,
        "themes": puzzle.themes,
        "attempt_count": len(puzzle.attempts),
        "needs_repeat": latest.needs_repeat if latest else False,
    }


def course_item(course) -> dict:
    return {
        "id": course.id,
        "title": course.title,
        "category": course.category,
        "level": course.level,
        "status": course.status,
        "progress_percent": course.progress_percent,
        "lines": course.lines,
    }


class ChessService:
    @staticmethod
    def dashboard() -> dict:
        games = ChessRepository.games(8)
        puzzles = ChessRepository.puzzles(20)
        due = [puzzle_item(item) for item in puzzles if puzzle_item(item)["needs_repeat"]]
        return {
            "games": [game_item(game) for game in games],
            "puzzles": [puzzle_item(puzzle) for puzzle in puzzles],
            "due_review": due,
            "courses": [course_item(course) for course in ChessRepository.courses()],
        }

    @staticmethod
    def complete_puzzle(
        puzzle: ChessPuzzle, *, wrong_count: int, reveal_used: bool, skipped: bool
    ) -> PuzzleAttempt:
        if wrong_count < 0:
            raise ValueError("Wrong move count must be non-negative.")
        clean = wrong_count == 0 and not reveal_used and not skipped
        attempt = PuzzleAttempt(
            puzzle=puzzle,
            status="skipped" if skipped else "completed",
            wrong_count=wrong_count,
            reveal_used=reveal_used,
            completed_clean=clean,
            needs_repeat=not clean,
            due_at=utc_now() + (timedelta(days=3) if clean else timedelta(days=1)),
            completed_at=utc_now(),
        )
        db.session.add(attempt)
        HistoryService.record(
            domain="chess",
            entity_type="puzzle",
            entity_id=puzzle.id,
            event_type="puzzle_attempt",
            label=f"Puzzle {puzzle.external_id}: {'clean' if clean else 'review needed'}",
            metadata={"wrong_count": wrong_count, "reveal_used": reveal_used},
        )
        db.session.commit()
        return attempt
