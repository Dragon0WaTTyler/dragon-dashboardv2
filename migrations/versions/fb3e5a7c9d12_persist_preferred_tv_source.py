"""persist the last working source for each logical TV channel

Revision ID: fb3e5a7c9d12
Revises: fa2d4e6c8b10
Create Date: 2026-08-24 02:20:00
"""

import sqlalchemy as sa
from alembic import op


revision = "fb3e5a7c9d12"
down_revision = "fa2d4e6c8b10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tv_channel_preferences") as batch:
        batch.add_column(
            sa.Column(
                "preferred_source_fingerprint",
                sa.String(length=64),
                nullable=False,
                server_default="",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tv_channel_preferences") as batch:
        batch.drop_column("preferred_source_fingerprint")
