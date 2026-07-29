"""add article content blocks

Revision ID: e6b4d2a1c8f7
Revises: 1f6c4b8d9e72
Create Date: 2026-07-28 00:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "e6b4d2a1c8f7"
down_revision = "1f6c4b8d9e72"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "articles",
        sa.Column(
            "content_blocks",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade():
    op.drop_column("articles", "content_blocks")
