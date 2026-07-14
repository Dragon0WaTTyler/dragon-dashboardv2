from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.shared.ids import new_id
from app.shared.time import utc_now


class GermanResource(db.Model):
    __tablename__ = "german_resources"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ger"))
    title: Mapped[str] = mapped_column(String(400), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(120), default="local", nullable=False)
    level: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class VocabularyItem(db.Model):
    __tablename__ = "german_vocabulary"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("voc"))
    term: Mapped[str] = mapped_column(String(240), nullable=False)
    meaning: Mapped[str] = mapped_column(String(500), nullable=False)
    example: Mapped[str] = mapped_column(Text, default="", nullable=False)
    level: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
