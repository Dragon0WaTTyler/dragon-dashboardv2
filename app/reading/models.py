from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.shared.ids import new_id
from app.shared.time import utc_now


class ReadingSource(db.Model):
    __tablename__ = "reading_sources"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rss"))
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    feed_url: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    health_state: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False)
    health_message: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    articles: Mapped[list[Article]] = relationship(back_populates="source")


class Article(db.Model):
    __tablename__ = "articles"
    __table_args__ = (Index("ix_articles_status_published", "status", "published_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("art"))
    source_id: Mapped[str | None] = mapped_column(ForeignKey("reading_sources.id"))
    external_id: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(600), nullable=False)
    url: Mapped[str] = mapped_column(String(1500), nullable=False)
    author: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    topic: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    image_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="unread", nullable=False)
    fulltext_state: Mapped[str] = mapped_column(String(30), default="not_requested", nullable=False)
    fulltext_error: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    history: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    source: Mapped[ReadingSource | None] = relationship(back_populates="articles")
