"""add explicit playback attempt history

Revision ID: c2f7a1d9e4b6
Revises: b1d2e3f4a5b6
Create Date: 2026-08-29 00:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "c2f7a1d9e4b6"
down_revision = "b1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playback_attempts",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "movie_id",
            sa.String(length=40),
            sa.ForeignKey("movies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "playback_source_id",
            sa.String(length=40),
            sa.ForeignKey("playback_sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("server_id", sa.String(length=120), nullable=False),
        sa.Column("content_id", sa.String(length=96), nullable=False),
        sa.Column("scope_key", sa.String(length=24), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("client_attempt_id", sa.String(length=80), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("startup_ms", sa.Integer(), nullable=True),
        sa.Column("quality", sa.String(length=80), nullable=False),
        sa.Column("language", sa.String(length=24), nullable=False),
        sa.Column("failure_reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id",
            "client_attempt_id",
            name="uq_playback_attempt_user_client_id",
        ),
    )
    op.create_index(
        "ix_playback_attempt_provider_time",
        "playback_attempts",
        ["provider", "created_at"],
    )
    op.create_index(
        "ix_playback_attempt_content_scope",
        "playback_attempts",
        ["movie_id", "scope_key", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_playback_attempt_content_scope", table_name="playback_attempts")
    op.drop_index("ix_playback_attempt_provider_time", table_name="playback_attempts")
    op.drop_table("playback_attempts")
