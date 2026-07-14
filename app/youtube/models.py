from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.shared.ids import new_id
from app.shared.time import utc_now


class YouTubeVideo(db.Model):
    __tablename__ = "youtube_videos"
    __table_args__ = (
        Index("ix_youtube_source_position", "source", "position"),
        Index("ix_youtube_group_channel", "group_name", "channel_title"),
        UniqueConstraint("source", "external_id", name="uq_youtube_source_external_id"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ytv"))
    external_id: Mapped[str] = mapped_column(String(80), nullable=False)
    playlist_item_id: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    group_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    channel_id: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    channel_title: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    thumbnail_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    watched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    removed_from_source: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    local_history: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
