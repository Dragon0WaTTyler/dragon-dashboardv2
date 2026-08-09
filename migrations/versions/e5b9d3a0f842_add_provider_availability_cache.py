"""add provider availability cache

Revision ID: e5b9d3a0f842
Revises: d4a8f2c9e731
Create Date: 2026-08-09 00:10:00
"""

import sqlalchemy as sa
from alembic import op

revision = "e5b9d3a0f842"
down_revision = "d4a8f2c9e731"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_availability",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "playback_source_id",
            sa.String(length=40),
            sa.ForeignKey("playback_sources.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("probe_level", sa.String(length=32), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("failure_reason", sa.String(length=500), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_provider_availability_status",
        "provider_availability",
        ["status", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_provider_availability_status", table_name="provider_availability")
    op.drop_table("provider_availability")
