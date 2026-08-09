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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.shared.ids import new_id
from app.shared.time import utc_now


class PlaybackSource(db.Model):
    __tablename__ = "playback_sources"
    __table_args__ = (
        Index("ix_playback_movie_status", "movie_id", "status"),
        UniqueConstraint(
            "movie_id",
            "scope_key",
            "provider",
            "provider_asset_id",
            name="uq_playback_source_provider_asset",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("src"))
    movie_id: Mapped[str] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    locator: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="available", nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    season: Mapped[int | None] = mapped_column(Integer)
    episode: Mapped[int | None] = mapped_column(Integer)
    source_role: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="local", nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), default="local", nullable=False)
    provider_asset_id: Mapped[str] = mapped_column(
        String(300), default=lambda: new_id("asset"), nullable=False
    )
    embed_reference: Mapped[str] = mapped_column(Text, default="", nullable=False)
    language: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    subtitle_languages: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    quality: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    match_confidence: Mapped[float | None] = mapped_column(Float)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    authorization_status: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority_override: Mapped[int | None] = mapped_column(Integer)
    scope_key: Mapped[str] = mapped_column(String(24), default="movie", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ProviderAvailability(db.Model):
    __tablename__ = "provider_availability"
    __table_args__ = (Index("ix_provider_availability_status", "status", "expires_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    playback_source_id: Mapped[str] = mapped_column(
        ForeignKey("playback_sources.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), default="UNKNOWN", nullable=False)
    probe_level: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    failure_reason: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlaybackProviderPreference(db.Model):
    __tablename__ = "playback_provider_preferences"

    provider: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    background_checks: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class ImportBatch(db.Model):
    __tablename__ = "playback_import_batches"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("impb"))
    import_method: Mapped[str] = mapped_column(String(20), nullable=False)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    filename: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accepted_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    review_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ImportRow(db.Model):
    __tablename__ = "playback_import_rows"
    __table_args__ = (Index("ix_playback_import_row_status", "batch_id", "match_status"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("impr"))
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("playback_import_batches.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    raw_reference: Mapped[str] = mapped_column(Text, default="", nullable=False)
    match_status: Mapped[str] = mapped_column(String(30), nullable=False)
    matched_movie_id: Mapped[str | None] = mapped_column(
        ForeignKey("movies.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    provider_asset_id: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    reason: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_playback_source_id: Mapped[str | None] = mapped_column(
        ForeignKey("playback_sources.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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
