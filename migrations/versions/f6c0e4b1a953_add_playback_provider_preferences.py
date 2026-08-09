"""add playback provider preferences

Revision ID: f6c0e4b1a953
Revises: e5b9d3a0f842
Create Date: 2026-08-09 00:20:00
"""

import sqlalchemy as sa
from alembic import op

revision = "f6c0e4b1a953"
down_revision = "e5b9d3a0f842"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playback_provider_preferences",
        sa.Column("provider", sa.String(length=40), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("background_checks", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("playback_provider_preferences")
