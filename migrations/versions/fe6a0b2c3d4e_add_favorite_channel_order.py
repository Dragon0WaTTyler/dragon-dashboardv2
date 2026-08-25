"""persist the manually arranged favorite channel order

Revision ID: fe6a0b2c3d4e
Revises: fd5a9b1c2e34
Create Date: 2026-08-24 15:00:00
"""

import sqlalchemy as sa
from alembic import op


revision = "fe6a0b2c3d4e"
down_revision = "fd5a9b1c2e34"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tv_channel_preferences") as batch:
        batch.add_column(sa.Column("favorite_position", sa.Integer(), nullable=True))
        batch.create_index(
            "ix_tv_channel_preferences_favorite_position", ["favorite_position"]
        )


def downgrade() -> None:
    with op.batch_alter_table("tv_channel_preferences") as batch:
        batch.drop_index("ix_tv_channel_preferences_favorite_position")
        batch.drop_column("favorite_position")
