"""Add persistent logical TV channel health.

Revision ID: d9a3e5b7c1f6
Revises: c8f2d4a6b0e5
"""

import sqlalchemy as sa
from alembic import op

revision = "d9a3e5b7c1f6"
down_revision = "c8f2d4a6b0e5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tv_channel_health",
        sa.Column("preference_key", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "source_fingerprint",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "failure_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "last_error", sa.String(length=240), nullable=False, server_default=""
        ),
        sa.PrimaryKeyConstraint("preference_key"),
    )
    op.create_index(
        "ix_tv_channel_health_status", "tv_channel_health", ["status"]
    )
    op.create_index(
        "ix_tv_channel_health_checked_at", "tv_channel_health", ["checked_at"]
    )


def downgrade():
    op.drop_index(
        "ix_tv_channel_health_checked_at", table_name="tv_channel_health"
    )
    op.drop_index("ix_tv_channel_health_status", table_name="tv_channel_health")
    op.drop_table("tv_channel_health")
