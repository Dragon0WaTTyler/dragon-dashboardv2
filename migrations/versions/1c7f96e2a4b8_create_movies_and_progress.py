"""create movies and progress

Revision ID: 1c7f96e2a4b8
Revises: 5f2c1b7a9d10
Create Date: 2026-07-14 02:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "1c7f96e2a4b8"
down_revision = "5f2c1b7a9d10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "movies",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("normalized_title", sa.String(length=300), nullable=False),
        sa.Column("original_title", sa.String(length=300), nullable=True),
        sa.Column("media_type", sa.String(length=20), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("runtime_minutes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("personal_score", sa.Float(), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("overview", sa.Text(), nullable=False),
        sa.Column("poster_url", sa.String(length=1000), nullable=False),
        sa.Column("trailer_url", sa.String(length=1000), nullable=False),
        sa.Column("genres", sa.JSON(), nullable=False),
        sa.Column("directors", sa.JSON(), nullable=False),
        sa.Column("cast", sa.JSON(), nullable=False),
        sa.Column("external_ids", sa.JSON(), nullable=False),
        sa.Column("metadata_state", sa.JSON(), nullable=False),
        sa.Column("watch_history", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_movies_normalized_title", "movies", ["normalized_title"])
    op.create_index("ix_movies_status", "movies", ["status"])
    op.create_index("ix_movies_status_title", "movies", ["status", "normalized_title"])
    op.create_index("ix_movies_year_score", "movies", ["year", "personal_score"])
    op.create_table(
        "movie_progress",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.String(length=40), nullable=False),
        sa.Column("current_seconds", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("client_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("movie_id"),
    )
    op.create_index("ix_movie_progress_movie_id", "movie_progress", ["movie_id"])


def downgrade():
    op.drop_index("ix_movie_progress_movie_id", table_name="movie_progress")
    op.drop_table("movie_progress")
    op.drop_index("ix_movies_year_score", table_name="movies")
    op.drop_index("ix_movies_status_title", table_name="movies")
    op.drop_index("ix_movies_status", table_name="movies")
    op.drop_index("ix_movies_normalized_title", table_name="movies")
    op.drop_table("movies")
