"""add soft creator preferences for personal tv

Revision ID: fd5a9b1c2e34
Revises: fc4e8a9d0b21
Create Date: 2026-08-24 14:40:00
"""

import sqlalchemy as sa
from alembic import op

revision = "fd5a9b1c2e34"
down_revision = "fc4e8a9d0b21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("personal_tv_preferences") as batch:
        batch.add_column(
            sa.Column("deprioritized_creators", sa.JSON(), nullable=False, server_default="[]")
        )


def downgrade() -> None:
    with op.batch_alter_table("personal_tv_preferences") as batch:
        batch.drop_column("deprioritized_creators")
