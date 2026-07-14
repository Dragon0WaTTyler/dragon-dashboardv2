"""add youtube reading and books

Revision ID: 7d4a9c2e61f3
Revises: 1c7f96e2a4b8
Create Date: 2026-07-14 03:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "7d4a9c2e61f3"
down_revision = "1c7f96e2a4b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "youtube_videos",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("external_id", sa.String(80), nullable=False, unique=True),
        sa.Column("playlist_item_id", sa.String(100), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("group_name", sa.String(160), nullable=False),
        sa.Column("channel_id", sa.String(100), nullable=False),
        sa.Column("channel_title", sa.String(240), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.String(1000), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("watched", sa.Boolean(), nullable=False),
        sa.Column("removed_from_source", sa.Boolean(), nullable=False),
        sa.Column("local_history", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_youtube_videos_source", "youtube_videos", ["source"])
    op.create_index("ix_youtube_videos_watched", "youtube_videos", ["watched"])
    op.create_index("ix_youtube_source_position", "youtube_videos", ["source", "position"])
    op.create_index("ix_youtube_group_channel", "youtube_videos", ["group_name", "channel_title"])
    op.create_table(
        "reading_sources",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("feed_url", sa.String(1000), nullable=False, unique=True),
        sa.Column("category", sa.String(120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("health_state", sa.String(30), nullable=False),
        sa.Column("health_message", sa.String(500), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "articles",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("source_id", sa.String(40), sa.ForeignKey("reading_sources.id")),
        sa.Column("external_id", sa.String(500), nullable=False),
        sa.Column("title", sa.String(600), nullable=False),
        sa.Column("url", sa.String(1500), nullable=False),
        sa.Column("author", sa.String(240), nullable=False),
        sa.Column("topic", sa.String(160), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("image_url", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("fulltext_state", sa.String(30), nullable=False),
        sa.Column("fulltext_error", sa.String(500), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_articles_status_published", "articles", ["status", "published_at"])
    op.create_table(
        "books",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("normalized_title", sa.String(500), nullable=False),
        sa.Column("authors", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("cover_url", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("current_page", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("personal_score", sa.Float()),
        sa.Column("published_year", sa.Integer()),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("external_ids", sa.JSON(), nullable=False),
        sa.Column("metadata_state", sa.JSON(), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_books_normalized_title", "books", ["normalized_title"])
    op.create_table(
        "quotes",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("book_id", sa.String(40), sa.ForeignKey("books.id", ondelete="CASCADE")),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer()),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_quotes_book_id", "quotes", ["book_id"])


def downgrade():
    op.drop_index("ix_quotes_book_id", table_name="quotes")
    op.drop_table("quotes")
    op.drop_index("ix_books_normalized_title", table_name="books")
    op.drop_table("books")
    op.drop_index("ix_articles_status_published", table_name="articles")
    op.drop_table("articles")
    op.drop_table("reading_sources")
    op.drop_index("ix_youtube_group_channel", table_name="youtube_videos")
    op.drop_index("ix_youtube_source_position", table_name="youtube_videos")
    op.drop_index("ix_youtube_videos_watched", table_name="youtube_videos")
    op.drop_index("ix_youtube_videos_source", table_name="youtube_videos")
    op.drop_table("youtube_videos")
