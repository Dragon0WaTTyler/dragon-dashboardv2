"""add isolated playback sources

Revision ID: af6c42e9b831
Revises: 93bfe4d276a0
Create Date: 2026-07-14 05:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "af6c42e9b831"
down_revision = "93bfe4d276a0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "playback_sources",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("movie_id", sa.String(40), sa.ForeignKey("movies.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_playback_movie_status", "playback_sources", ["movie_id", "status"])
    op.create_table(
        "magnet_candidates",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("movie_id", sa.String(40), sa.ForeignKey("movies.id", ondelete="CASCADE")),
        sa.Column("info_hash", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(500), nullable=False),
        sa.Column("magnet_uri", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("review_state", sa.String(30), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_magnet_candidates_info_hash", "magnet_candidates", ["info_hash"])


def downgrade():
    op.drop_index("ix_magnet_candidates_info_hash", table_name="magnet_candidates")
    op.drop_table("magnet_candidates")
    op.drop_index("ix_playback_movie_status", table_name="playback_sources")
    op.drop_table("playback_sources")
