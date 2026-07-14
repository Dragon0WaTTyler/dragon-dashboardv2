from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.shared.ids import new_id
from app.shared.time import utc_now


class Movie(db.Model):
    __tablename__ = "movies"
    __table_args__ = (
        Index("ix_movies_status_title", "status", "normalized_title"),
        Index("ix_movies_year_score", "year", "personal_score"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mov"))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    original_title: Mapped[str | None] = mapped_column(String(300))
    media_type: Mapped[str] = mapped_column(String(20), default="movie", nullable=False)
    year: Mapped[int | None] = mapped_column(Integer)
    runtime_minutes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False, index=True)
    personal_score: Mapped[float | None] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(80), default="local", nullable=False)
    overview: Mapped[str] = mapped_column(Text, default="", nullable=False)
    poster_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    trailer_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    genres: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    directors: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    cast: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    external_ids: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    metadata_state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    watch_history: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    progress: Mapped[MovieProgress | None] = relationship(
        back_populates="movie", cascade="all, delete-orphan", uselist=False
    )


class MovieProgress(db.Model):
    __tablename__ = "movie_progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    movie_id: Mapped[str] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), unique=True, index=True
    )
    current_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    client_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    movie: Mapped[Movie] = relationship(back_populates="progress")
