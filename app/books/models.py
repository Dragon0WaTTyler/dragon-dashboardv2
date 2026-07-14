from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.shared.ids import new_id
from app.shared.time import utc_now


class Book(db.Model):
    __tablename__ = "books"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("bok"))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    authors: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cover_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="want_to_read", nullable=False)
    current_page: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    personal_score: Mapped[float | None] = mapped_column(Float)
    published_year: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(80), default="local", nullable=False)
    external_ids: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    metadata_state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    history: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    quotes: Mapped[list[Quote]] = relationship(back_populates="book", cascade="all, delete-orphan")


class Quote(db.Model):
    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("quo"))
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    book: Mapped[Book] = relationship(back_populates="quotes")
