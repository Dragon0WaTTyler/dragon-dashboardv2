from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.books.identity import new_dragon_book_id
from app.extensions import db
from app.shared.ids import new_id
from app.shared.time import utc_now


class Book(db.Model):
    __tablename__ = "books"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("bok"))
    dragon_book_id: Mapped[str] = mapped_column(
        String(80), default=new_dragon_book_id, unique=True, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    original_title: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    authors: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    additional_authors: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cover_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="wishlist", nullable=False)
    current_page: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    personal_score: Mapped[float | None] = mapped_column(Float)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    personal_tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    collections: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    personal_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    edition_language: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    original_language: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    translator: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    publisher: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    published_year: Mapped[int | None] = mapped_column(Integer)
    isbn_10: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    isbn_13: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    series_name: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    series_position: Mapped[float | None] = mapped_column(Float)
    subjects: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    genres: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source: Mapped[str] = mapped_column(String(80), default="local", nullable=False)
    external_ids: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    metadata_status: Mapped[str] = mapped_column(String(40), default="missing", nullable=False)
    metadata_confidence: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    metadata_sources: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    metadata_state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    history: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    last_metadata_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    quotes: Mapped[list[Quote]] = relationship(back_populates="book", cascade="all, delete-orphan")
    editions: Mapped[list[BookEdition]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )
    audiobooks: Mapped[list[AudiobookEdition]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )
    availability_candidates: Mapped[list[AvailabilityCandidate]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )


class BookEdition(db.Model):
    __tablename__ = "book_editions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("bed"))
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    language: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    translator: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    publisher: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    edition_number: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    isbn_10: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    isbn_13: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    openlibrary_edition_id: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    google_books_volume_id: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    cover_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    description_override: Mapped[str] = mapped_column(Text, default="", nullable=False)
    edition_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(40), default="needs_review", nullable=False
    )
    primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    book: Mapped[Book] = relationship(back_populates="editions")
    text_assets: Mapped[list[TextAsset]] = relationship(
        back_populates="edition", cascade="all, delete-orphan"
    )


class TextAsset(db.Model):
    __tablename__ = "book_text_assets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("bta"))
    edition_id: Mapped[str] = mapped_column(
        ForeignKey("book_editions.id", ondelete="CASCADE"), index=True
    )
    format: Mapped[str] = mapped_column(String(12), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), default="local", nullable=False)
    source_reference: Mapped[str] = mapped_column(Text, default="", nullable=False)
    local_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    filename: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(128), default="", nullable=False, index=True)
    availability_status: Mapped[str] = mapped_column(
        String(40), default="available", nullable=False
    )
    verification_status: Mapped[str] = mapped_column(
        String(40), default="needs_review", nullable=False
    )
    preferred_for_kindle: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    edition: Mapped[BookEdition] = relationship(back_populates="text_assets")


class AudiobookEdition(db.Model):
    __tablename__ = "audiobook_editions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("aud"))
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    related_text_edition_id: Mapped[str | None] = mapped_column(
        ForeignKey("book_editions.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    language: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    narrator: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    additional_narrators: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    publisher: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    release_year: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chapter_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    abridgement_type: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    production_type: Mapped[str] = mapped_column(
        String(40), default="single_narrator", nullable=False
    )
    cover_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    audiobook_isbn: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(40), default="needs_review", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    book: Mapped[Book] = relationship(back_populates="audiobooks")
    assets: Mapped[list[AudiobookAsset]] = relationship(
        back_populates="audiobook", cascade="all, delete-orphan"
    )


class AudiobookAsset(db.Model):
    __tablename__ = "audiobook_assets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("aua"))
    audiobook_id: Mapped[str] = mapped_column(
        ForeignKey("audiobook_editions.id", ondelete="CASCADE"), index=True
    )
    format: Mapped[str] = mapped_column(String(12), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), default="local", nullable=False)
    source_reference: Mapped[str] = mapped_column(Text, default="", nullable=False)
    local_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    filename: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(128), default="", nullable=False, index=True)
    availability_status: Mapped[str] = mapped_column(
        String(40), default="available", nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    audiobook: Mapped[AudiobookEdition] = relationship(back_populates="assets")


class AvailabilityCandidate(db.Model):
    __tablename__ = "book_availability_candidates"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("bac"))
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    edition_id: Mapped[str | None] = mapped_column(
        ForeignKey("book_editions.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    format_guess: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    language_guess: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    match_confidence: Mapped[str] = mapped_column(
        String(40), default="needs_review", nullable=False
    )
    source_reference: Mapped[str] = mapped_column(Text, default="", nullable=False)
    review_state: Mapped[str] = mapped_column(
        String(40), default="review_required", nullable=False
    )
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    book: Mapped[Book] = relationship(back_populates="availability_candidates")


class Quote(db.Model):
    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("quo"))
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    book: Mapped[Book] = relationship(back_populates="quotes")
