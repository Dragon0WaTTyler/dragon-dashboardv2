"""add knowledge identity v1

Revision ID: f2a4d8c9e731
Revises: e8b6c2a9f4d1
Create Date: 2026-07-19 23:30:00.000000
"""

from __future__ import annotations

# ruff: noqa: E501
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "f2a4d8c9e731"
down_revision = "e8b6c2a9f4d1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("books") as batch_op:
        batch_op.add_column(sa.Column("dragon_book_id", sa.String(80), nullable=True))
        batch_op.add_column(sa.Column("original_title", sa.String(500), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("additional_authors", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("favorite", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("personal_tags", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("collections", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("personal_notes", sa.Text(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("edition_language", sa.String(80), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("original_language", sa.String(80), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("translator", sa.String(240), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("publisher", sa.String(240), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("isbn_10", sa.String(20), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("isbn_13", sa.String(20), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("series_name", sa.String(240), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("series_position", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("subjects", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("genres", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("metadata_status", sa.String(40), nullable=False, server_default="missing"))
        batch_op.add_column(sa.Column("metadata_confidence", sa.String(40), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("metadata_sources", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("last_metadata_refresh_at", sa.DateTime(timezone=True), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id FROM books WHERE dragon_book_id IS NULL")).fetchall()
    for row in rows:
        bind.execute(
            sa.text("UPDATE books SET dragon_book_id = :dragon_book_id WHERE id = :id"),
            {"dragon_book_id": f"dragon-book-{uuid4().hex}", "id": row.id},
        )
    op.create_index("ix_books_dragon_book_id", "books", ["dragon_book_id"], unique=True)

    op.create_table(
        "book_editions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("book_id", sa.String(40), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("subtitle", sa.String(500), nullable=False),
        sa.Column("language", sa.String(80), nullable=False),
        sa.Column("translator", sa.String(240), nullable=False),
        sa.Column("publisher", sa.String(240), nullable=False),
        sa.Column("publication_year", sa.Integer()),
        sa.Column("edition_number", sa.String(80), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("isbn_10", sa.String(20), nullable=False),
        sa.Column("isbn_13", sa.String(20), nullable=False),
        sa.Column("openlibrary_edition_id", sa.String(80), nullable=False),
        sa.Column("google_books_volume_id", sa.String(120), nullable=False),
        sa.Column("cover_url", sa.String(1000), nullable=False),
        sa.Column("description_override", sa.Text(), nullable=False),
        sa.Column("edition_notes", sa.Text(), nullable=False),
        sa.Column("verification_status", sa.String(40), nullable=False),
        sa.Column("primary", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_book_editions_book_id", "book_editions", ["book_id"])

    op.create_table(
        "book_text_assets",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("edition_id", sa.String(40), sa.ForeignKey("book_editions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("format", sa.String(12), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("file_hash", sa.String(128), nullable=False),
        sa.Column("availability_status", sa.String(40), nullable=False),
        sa.Column("verification_status", sa.String(40), nullable=False),
        sa.Column("preferred_for_kindle", sa.Boolean(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_book_text_assets_edition_id", "book_text_assets", ["edition_id"])
    op.create_index("ix_book_text_assets_file_hash", "book_text_assets", ["file_hash"])

    op.create_table(
        "audiobook_editions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("book_id", sa.String(40), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("related_text_edition_id", sa.String(40), sa.ForeignKey("book_editions.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("language", sa.String(80), nullable=False),
        sa.Column("narrator", sa.String(240), nullable=False),
        sa.Column("additional_narrators", sa.JSON(), nullable=False),
        sa.Column("publisher", sa.String(240), nullable=False),
        sa.Column("release_year", sa.Integer()),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("chapter_count", sa.Integer(), nullable=False),
        sa.Column("abridgement_type", sa.String(40), nullable=False),
        sa.Column("production_type", sa.String(40), nullable=False),
        sa.Column("cover_url", sa.String(1000), nullable=False),
        sa.Column("audiobook_isbn", sa.String(20), nullable=False),
        sa.Column("verification_status", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audiobook_editions_book_id", "audiobook_editions", ["book_id"])

    op.create_table(
        "audiobook_assets",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("audiobook_id", sa.String(40), sa.ForeignKey("audiobook_editions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("format", sa.String(12), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("file_hash", sa.String(128), nullable=False),
        sa.Column("availability_status", sa.String(40), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_audiobook_assets_audiobook_id", "audiobook_assets", ["audiobook_id"])
    op.create_index("ix_audiobook_assets_file_hash", "audiobook_assets", ["file_hash"])

    op.create_table(
        "book_availability_candidates",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("book_id", sa.String(40), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("edition_id", sa.String(40), sa.ForeignKey("book_editions.id", ondelete="SET NULL")),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("format_guess", sa.String(20), nullable=False),
        sa.Column("language_guess", sa.String(80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("match_confidence", sa.String(40), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("review_state", sa.String(40), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_book_availability_candidates_book_id", "book_availability_candidates", ["book_id"])


def downgrade():
    op.drop_index("ix_book_availability_candidates_book_id", table_name="book_availability_candidates")
    op.drop_table("book_availability_candidates")
    op.drop_index("ix_audiobook_assets_file_hash", table_name="audiobook_assets")
    op.drop_index("ix_audiobook_assets_audiobook_id", table_name="audiobook_assets")
    op.drop_table("audiobook_assets")
    op.drop_index("ix_audiobook_editions_book_id", table_name="audiobook_editions")
    op.drop_table("audiobook_editions")
    op.drop_index("ix_book_text_assets_file_hash", table_name="book_text_assets")
    op.drop_index("ix_book_text_assets_edition_id", table_name="book_text_assets")
    op.drop_table("book_text_assets")
    op.drop_index("ix_book_editions_book_id", table_name="book_editions")
    op.drop_table("book_editions")
    op.drop_index("ix_books_dragon_book_id", table_name="books")
    with op.batch_alter_table("books") as batch_op:
        batch_op.drop_column("last_metadata_refresh_at")
        batch_op.drop_column("metadata_sources")
        batch_op.drop_column("metadata_confidence")
        batch_op.drop_column("metadata_status")
        batch_op.drop_column("genres")
        batch_op.drop_column("subjects")
        batch_op.drop_column("series_position")
        batch_op.drop_column("series_name")
        batch_op.drop_column("isbn_13")
        batch_op.drop_column("isbn_10")
        batch_op.drop_column("publisher")
        batch_op.drop_column("translator")
        batch_op.drop_column("original_language")
        batch_op.drop_column("edition_language")
        batch_op.drop_column("personal_notes")
        batch_op.drop_column("collections")
        batch_op.drop_column("personal_tags")
        batch_op.drop_column("favorite")
        batch_op.drop_column("additional_authors")
        batch_op.drop_column("original_title")
        batch_op.drop_column("dragon_book_id")
