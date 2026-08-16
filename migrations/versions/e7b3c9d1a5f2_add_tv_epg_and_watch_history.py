"""add TV EPG cache and watch history

Revision ID: e7b3c9d1a5f2
Revises: d6a4f8b1c320
Create Date: 2026-08-16 00:35:00
"""

import sqlalchemy as sa
from alembic import op

revision = "e7b3c9d1a5f2"
down_revision = "d6a4f8b1c320"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tv_channel_preferences") as batch_op:
        batch_op.add_column(sa.Column("last_watched_at", sa.DateTime(timezone=True)))
        batch_op.add_column(
            sa.Column("watch_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.create_index(
            "ix_tv_channel_preferences_last_watched_at", ["last_watched_at"]
        )

    op.create_table(
        "tv_programmes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tvg_id", sa.String(300), nullable=False),
        sa.Column("title", sa.String(600), nullable=False),
        sa.Column("subtitle", sa.String(600), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(500), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tvg_id", "starts_at", "title", name="uq_tv_programme_slot"),
    )
    op.create_index("ix_tv_programmes_tvg_id", "tv_programmes", ["tvg_id"])
    op.create_index("ix_tv_programmes_starts_at", "tv_programmes", ["starts_at"])
    op.create_index("ix_tv_programmes_ends_at", "tv_programmes", ["ends_at"])
    op.create_index(
        "ix_tv_programmes_channel_window",
        "tv_programmes",
        ["tvg_id", "starts_at", "ends_at"],
    )

    op.create_table(
        "tv_epg_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="idle"),
        sa.Column("message", sa.String(300), nullable=False, server_default=""),
        sa.Column("last_error", sa.String(500), nullable=False, server_default=""),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("matched_channels", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("programme_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_tv_epg_state_last_success_at", "tv_epg_state", ["last_success_at"])


def downgrade():
    op.drop_index("ix_tv_epg_state_last_success_at", table_name="tv_epg_state")
    op.drop_table("tv_epg_state")
    op.drop_index("ix_tv_programmes_channel_window", table_name="tv_programmes")
    op.drop_index("ix_tv_programmes_ends_at", table_name="tv_programmes")
    op.drop_index("ix_tv_programmes_starts_at", table_name="tv_programmes")
    op.drop_index("ix_tv_programmes_tvg_id", table_name="tv_programmes")
    op.drop_table("tv_programmes")
    with op.batch_alter_table("tv_channel_preferences") as batch_op:
        batch_op.drop_index("ix_tv_channel_preferences_last_watched_at")
        batch_op.drop_column("watch_count")
        batch_op.drop_column("last_watched_at")
