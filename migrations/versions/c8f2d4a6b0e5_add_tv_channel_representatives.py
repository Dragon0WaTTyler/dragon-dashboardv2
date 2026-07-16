"""Add a materialized representative for each logical TV channel.

Revision ID: c8f2d4a6b0e5
Revises: b7e1c3f5a9d4
"""

import sqlalchemy as sa
from alembic import op

revision = "c8f2d4a6b0e5"
down_revision = "b7e1c3f5a9d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tv_channel_representatives",
        sa.Column("preference_key", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["channel_id"], ["tv_channels.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("preference_key"),
        sa.UniqueConstraint("channel_id"),
    )
    op.execute(
        """
        INSERT INTO tv_channel_representatives (preference_key, channel_id)
        SELECT channels.preference_key, MAX(channels.id)
        FROM tv_channels AS channels
        JOIN tv_playlists AS playlists ON playlists.id = channels.playlist_id
        WHERE playlists.imported = 1 AND playlists.available = 1
        GROUP BY channels.preference_key
        """
    )


def downgrade():
    op.drop_table("tv_channel_representatives")
