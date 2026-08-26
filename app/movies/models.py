from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.shared.ids import new_id
from app.shared.time import utc_now


def canonical_media_key(
    *,
    movie_id: str,
    media_type: str,
    external_ids: dict | None = None,
) -> str:
    """Return the stable V2 identity for one persisted Movie record."""

    normalized_type = "tv" if str(media_type).strip().lower() == "tv" else "movie"
    tmdb_id = str((external_ids or {}).get("tmdb_id") or "").strip()
    if tmdb_id.isdigit() and int(tmdb_id) > 0:
        return f"{normalized_type}:{int(tmdb_id)}"
    return f"local:{normalized_type}:{movie_id}"


def progress_scope_key(*, season: int | None, episode: int | None) -> str:
    """Return the persistence scope for movie- or episode-level progress."""

    if season is None and episode is None:
        return "movie"
    if season is None or episode is None or int(season) < 0 or int(episode) < 1:
        raise ValueError("Progress requires a movie or a complete season/episode pair.")
    return f"s{int(season):02d}e{int(episode):02d}"


class Movie(db.Model):
    __tablename__ = "movies"
    __table_args__ = (
        Index("ix_movies_status_title", "status", "normalized_title"),
        Index("ix_movies_year_score", "year", "personal_score"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mov"))
    media_key: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
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

    progress_entries: Mapped[list[MovieProgress]] = relationship(
        back_populates="movie",
        cascade="all, delete-orphan",
        order_by="MovieProgress.updated_at.desc()",
    )
    progress: Mapped[MovieProgress | None] = relationship(
        primaryjoin=lambda: and_(
            Movie.id == MovieProgress.movie_id,
            MovieProgress.season.is_(None),
            MovieProgress.episode.is_(None),
        ),
        uselist=False,
        viewonly=True,
        overlaps="movie,progress_entries",
    )
    library_entry: Mapped[MovieLibraryEntry | None] = relationship(
        back_populates="movie",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="MovieLibraryEntry.movie_id",
    )


class MovieLibraryEntry(db.Model):
    """Dragon-owned personal state, deliberately separate from catalog metadata."""

    __tablename__ = "movie_library_entries"

    media_key: Mapped[str] = mapped_column(
        ForeignKey("movies.media_key", ondelete="CASCADE"), primary_key=True
    )
    movie_id: Mapped[str] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    lifecycle_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    personal_rating: Mapped[float | None] = mapped_column(Float)
    personal_label: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    first_watched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_watched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manual_lifecycle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    movie: Mapped[Movie] = relationship(
        back_populates="library_entry",
        foreign_keys=[movie_id],
    )


class MovieCustomList(db.Model):
    """A user-owned collection, deliberately independent from lifecycle state."""

    __tablename__ = "movie_custom_lists"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id("mls")
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    items: Mapped[list[MovieCustomListItem]] = relationship(
        back_populates="custom_list", cascade="all, delete-orphan", order_by="MovieCustomListItem.position"
    )


class MovieCustomListItem(db.Model):
    __tablename__ = "movie_custom_list_items"
    __table_args__ = (Index("ix_movie_custom_list_items_movie", "movie_id"),)

    custom_list_id: Mapped[str] = mapped_column(
        ForeignKey("movie_custom_lists.id", ondelete="CASCADE"), primary_key=True
    )
    movie_id: Mapped[str] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    custom_list: Mapped[MovieCustomList] = relationship(back_populates="items")
    movie: Mapped[Movie] = relationship()


class MovieProgress(db.Model):
    __tablename__ = "movie_progress"
    __table_args__ = (
        UniqueConstraint("movie_id", "scope_key", name="uq_movie_progress_scope"),
        Index("ix_movie_progress_scope", "movie_id", "scope_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    movie_id: Mapped[str] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), index=True
    )
    scope_key: Mapped[str] = mapped_column(String(24), nullable=False, default="movie")
    season: Mapped[int | None] = mapped_column(Integer)
    episode: Mapped[int | None] = mapped_column(Integer)
    current_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    client_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    movie: Mapped[Movie] = relationship(back_populates="progress_entries", overlaps="progress")


@event.listens_for(Movie, "before_insert")
def _assign_movie_media_key(_mapper, _connection, target: Movie) -> None:
    if not target.id:
        target.id = new_id("mov")
    if not target.media_key:
        target.media_key = canonical_media_key(
            movie_id=target.id,
            media_type=target.media_type,
            external_ids=target.external_ids,
        )


@event.listens_for(MovieProgress, "before_insert")
@event.listens_for(MovieProgress, "before_update")
def _assign_progress_scope_key(_mapper, _connection, target: MovieProgress) -> None:
    target.scope_key = progress_scope_key(season=target.season, episode=target.episode)
