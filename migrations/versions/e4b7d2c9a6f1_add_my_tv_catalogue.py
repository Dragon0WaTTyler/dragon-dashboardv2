"""add my tv catalogue

Revision ID: e4b7d2c9a6f1
Revises: c3e7a1f4902b
Create Date: 2026-07-15 04:30:00
"""

import sqlalchemy as sa
from alembic import op

revision = "e4b7d2c9a6f1"
down_revision = "c3e7a1f4902b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tv_playlists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("github_path", sa.String(500), nullable=False, unique=True),
        sa.Column("source_url", sa.String(2000), nullable=False),
        sa.Column("source_sha", sa.String(80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("imported", sa.Boolean(), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("channel_count", sa.Integer(), nullable=False),
        sa.Column("group_count", sa.Integer(), nullable=False),
        sa.Column("sync_status", sa.String(30), nullable=False),
        sa.Column("sync_error", sa.Text(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "tv_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "playlist_id",
            sa.Integer(),
            sa.ForeignKey("tv_playlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("channel_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("playlist_id", "name", name="uq_tv_group_playlist_name"),
    )
    op.create_index("ix_tv_groups_playlist_id", "tv_groups", ["playlist_id"])
    op.create_table(
        "tv_channels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "playlist_id",
            sa.Integer(),
            sa.ForeignKey("tv_playlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("tv_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(600), nullable=False),
        sa.Column("tvg_id", sa.String(300), nullable=False),
        sa.Column("tvg_name", sa.String(600), nullable=False),
        sa.Column("logo_url", sa.String(2000), nullable=False),
        sa.Column("stream_url", sa.Text(), nullable=False),
        sa.Column("stream_kind", sa.String(30), nullable=False),
        sa.Column("enabled_override", sa.Boolean()),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("last_seen_sync", sa.String(40), nullable=False),
        sa.UniqueConstraint(
            "playlist_id", "external_key", name="uq_tv_channel_external_key"
        ),
    )
    op.create_index("ix_tv_channels_playlist_id", "tv_channels", ["playlist_id"])
    op.create_index("ix_tv_channels_group_id", "tv_channels", ["group_id"])
    op.create_index(
        "ix_tv_channels_group_position", "tv_channels", ["group_id", "position"]
    )
    op.create_index("ix_tv_channels_name", "tv_channels", ["name"])


def downgrade():
    op.drop_index("ix_tv_channels_name", table_name="tv_channels")
    op.drop_index("ix_tv_channels_group_position", table_name="tv_channels")
    op.drop_index("ix_tv_channels_group_id", table_name="tv_channels")
    op.drop_index("ix_tv_channels_playlist_id", table_name="tv_channels")
    op.drop_table("tv_channels")
    op.drop_index("ix_tv_groups_playlist_id", table_name="tv_groups")
    op.drop_table("tv_groups")
    op.drop_table("tv_playlists")
