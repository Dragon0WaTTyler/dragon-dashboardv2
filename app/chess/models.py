from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.shared.ids import new_id
from app.shared.time import utc_now


class ChessGame(db.Model):
    __tablename__ = "chess_games"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("gam"))
    external_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    white: Mapped[str] = mapped_column(String(180), nullable=False)
    black: Mapped[str] = mapped_column(String(180), nullable=False)
    user_color: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    user_result: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    result: Mapped[str] = mapped_column(String(20), default="*", nullable=False)
    played_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_class: Mapped[str] = mapped_column(String(40), default="other", nullable=False)
    time_control: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    opening: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    pgn: Mapped[str] = mapped_column(Text, default="", nullable=False)
    moves: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    rated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ChessPuzzle(db.Model):
    __tablename__ = "chess_puzzles"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("puz"))
    external_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="lichess", nullable=False)
    fen: Mapped[str] = mapped_column(String(200), nullable=False)
    moves: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    rating: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    themes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    opening_tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    attempts: Mapped[list[PuzzleAttempt]] = relationship(
        back_populates="puzzle", cascade="all, delete-orphan"
    )


class PuzzleAttempt(db.Model):
    __tablename__ = "puzzle_attempts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("pat"))
    puzzle_id: Mapped[str] = mapped_column(ForeignKey("chess_puzzles.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(30), default="started", nullable=False)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reveal_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_clean: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    needs_repeat: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    puzzle: Mapped[ChessPuzzle] = relationship(back_populates="attempts")


class ChessCourse(db.Model):
    __tablename__ = "chess_courses"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("crs"))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(40), default="opening", nullable=False)
    level: Mapped[str] = mapped_column(String(40), default="intermediate", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="planned", nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lines: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
