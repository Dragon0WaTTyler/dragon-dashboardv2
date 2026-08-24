from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.shared.ids import new_id
from app.shared.time import utc_now


class ProgrammingPreferences(db.Model):
    """Explicit preferences only; inferred behaviour does not belong here."""

    __tablename__ = "personal_tv_preferences"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    default_duration_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    selected_groups: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    avoid_watched: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    no_shorts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    preferred_topics: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    preferred_formats: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    preferred_languages: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    preferred_creators: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    blocked_creators: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    avoided_keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    discovery_level: Mapped[str] = mapped_column(String(20), default="balanced", nullable=False)
    source_quality: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    daypart_profiles: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class TVSession(db.Model):
    """Runtime state for one programmed session, never a replacement for source state."""

    __tablename__ = "personal_tv_sessions"
    __table_args__ = (Index("ix_personal_tv_sessions_state_updated", "state", "updated_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("tvs"))
    state: Mapped[str] = mapped_column(String(20), default="planned", nullable=False)
    requested_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    request_groups: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    avoid_watched: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    no_shorts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    request_intent: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    programming_version: Mapped[str] = mapped_column(String(40), default="v0", nullable=False)
    current_item_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ending_reason: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    items: Mapped[list[TVSessionItem]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="TVSessionItem.position"
    )


class TVSessionItem(db.Model):
    """A snapshot is stored so a source change cannot rewrite a running programme."""

    __tablename__ = "personal_tv_session_items"
    __table_args__ = (
        Index("ix_personal_tv_session_items_session_position", "session_id", "position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("personal_tv_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(80), nullable=False)
    content_id: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    creator: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    content_type: Mapped[str] = mapped_column(String(40), default="video", nullable=False)
    language: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    program_role: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    story_key: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    thumbnail_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_selected: Mapped[str] = mapped_column(Text, default="", nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    completion_ratio: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    skip_reason: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    replaced_item_id: Mapped[int | None] = mapped_column(Integer)

    session: Mapped[TVSession] = relationship(back_populates="items")


class PersonalTVFeedback(db.Model):
    """Explicit feedback; skips are retained as neutral events until a reason is supplied."""

    __tablename__ = "personal_tv_feedback"
    __table_args__ = (Index("ix_personal_tv_feedback_kind_created", "kind", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("personal_tv_sessions.id", ondelete="SET NULL"), index=True
    )
    session_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("personal_tv_session_items.id", ondelete="SET NULL"), index=True
    )
    candidate_id: Mapped[str] = mapped_column(String(80), default="", nullable=False, index=True)
    creator: Mapped[str] = mapped_column(String(240), default="", nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class PreparedTVProgram(db.Model):
    """A replaceable, user-owned future programme. It never mutates a completed session."""

    __tablename__ = "personal_tv_prepared_programs"
    __table_args__ = (Index("ix_personal_tv_prepared_programs_start", "starts_at", "state"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("tvp"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="prepared", nullable=False)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("personal_tv_sessions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
