from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.shared.ids import new_id
from app.shared.time import utc_now


class PlaybackSource(db.Model):
    __tablename__ = "playback_sources"
    __table_args__ = (Index("ix_playback_movie_status", "movie_id", "status"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("src"))
    movie_id: Mapped[str] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    locator: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="available", nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class MagnetCandidate(db.Model):
    __tablename__ = "magnet_candidates"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mag"))
    movie_id: Mapped[str] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"))
    info_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    magnet_uri: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    review_state: Mapped[str] = mapped_column(String(30), default="review_required", nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
