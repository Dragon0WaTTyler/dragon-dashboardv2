from __future__ import annotations

from sqlalchemy.orm import selectinload

from app.chess.models import ChessCourse, ChessGame, ChessPuzzle
from app.extensions import db


class ChessRepository:
    @staticmethod
    def games(limit: int = 30) -> list[ChessGame]:
        return list(
            db.session.scalars(
                db.select(ChessGame).order_by(ChessGame.played_at.desc()).limit(limit)
            )
        )

    @staticmethod
    def game(game_id: str) -> ChessGame | None:
        return db.session.get(ChessGame, game_id)

    @staticmethod
    def puzzles(limit: int = 30) -> list[ChessPuzzle]:
        return list(
            db.session.scalars(
                db.select(ChessPuzzle)
                .options(selectinload(ChessPuzzle.attempts))
                .order_by(ChessPuzzle.rating)
                .limit(limit)
            )
        )

    @staticmethod
    def puzzle(puzzle_id: str) -> ChessPuzzle | None:
        return db.session.scalar(
            db.select(ChessPuzzle)
            .options(selectinload(ChessPuzzle.attempts))
            .where(ChessPuzzle.id == puzzle_id)
        )

    @staticmethod
    def courses() -> list[ChessCourse]:
        return list(db.session.scalars(db.select(ChessCourse).order_by(ChessCourse.title)))
