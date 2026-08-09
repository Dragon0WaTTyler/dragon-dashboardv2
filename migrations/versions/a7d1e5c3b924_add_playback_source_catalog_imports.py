"""add playback source catalog imports

Revision ID: a7d1e5c3b924
Revises: f6c0e4b1a953
Create Date: 2026-08-09 05:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "a7d1e5c3b924"
down_revision = "f6c0e4b1a953"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playback_import_batches",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("import_method", sa.String(length=20), nullable=False),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("filename", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("accepted_rows", sa.Integer(), nullable=False),
        sa.Column("review_rows", sa.Integer(), nullable=False),
        sa.Column("rejected_rows", sa.Integer(), nullable=False),
        sa.Column("error_rows", sa.Integer(), nullable=False),
    )
    op.create_table(
        "playback_import_rows",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(length=40),
            sa.ForeignKey("playback_import_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=False),
        sa.Column("raw_reference", sa.Text(), nullable=False),
        sa.Column("match_status", sa.String(length=30), nullable=False),
        sa.Column(
            "matched_movie_id",
            sa.String(length=40),
            sa.ForeignKey("movies.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_asset_id", sa.String(length=300), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_playback_source_id",
            sa.String(length=40),
            sa.ForeignKey("playback_sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_playback_import_row_status",
        "playback_import_rows",
        ["batch_id", "match_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_playback_import_row_status", table_name="playback_import_rows")
    op.drop_table("playback_import_rows")
    op.drop_table("playback_import_batches")
