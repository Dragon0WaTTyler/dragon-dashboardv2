"""persist tv bouquet preferences

Revision ID: d6a4f8b1c320
Revises: c5f9a7d2e164
Create Date: 2026-08-15 04:30:00
"""

import sqlalchemy as sa
from alembic import op

revision = "d6a4f8b1c320"
down_revision = "c5f9a7d2e164"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tv_theme_preferences",
        sa.Column("theme_key", sa.String(240), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("channel_policy", sa.Boolean()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO tv_theme_preferences
                (theme_key, enabled, channel_policy, created_at, updated_at)
            SELECT key, enabled, channel_policy, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM tv_themes
            WHERE enabled = 1 OR channel_policy IS NOT NULL
            """
        )
    )


def downgrade():
    op.drop_table("tv_theme_preferences")
