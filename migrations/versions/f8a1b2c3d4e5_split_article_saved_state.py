"""split article saved state from reading progress

Revision ID: f8a1b2c3d4e5
Revises: f7a8b9c0d1e2
Create Date: 2026-08-22 12:00:00
"""

import sqlalchemy as sa
from alembic import op


revision = "f8a1b2c3d4e5"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("articles") as batch:
        batch.add_column(
            sa.Column("is_saved", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.execute(sa.text("UPDATE articles SET is_saved = 1, status = 'unread' WHERE status = 'saved'"))
    with op.batch_alter_table("articles") as batch:
        batch.alter_column("is_saved", server_default=None)


def downgrade() -> None:
    op.execute(sa.text("UPDATE articles SET status = 'saved' WHERE is_saved = 1"))
    with op.batch_alter_table("articles") as batch:
        batch.drop_column("is_saved")
