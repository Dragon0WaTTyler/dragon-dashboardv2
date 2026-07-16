"""merge all TV sources into one automatic catalogue

Revision ID: b7e1c3f5a9d4
Revises: a6d9e2f4b8c3
Create Date: 2026-07-15 06:55:00.000000
"""

from alembic import op

revision = "b7e1c3f5a9d4"
down_revision = "a6d9e2f4b8c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE tv_playlists SET enabled = 1")


def downgrade() -> None:
    op.execute("UPDATE tv_playlists SET enabled = 0")
