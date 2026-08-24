"""add personal tv catalogue memberships and runtime playhead

Revision ID: fc4e8a9d0b21
Revises: fb3e5a7c9d12
Create Date: 2026-08-24 14:20:00
"""

import sqlalchemy as sa
from alembic import op

revision = "fc4e8a9d0b21"
down_revision = "fb3e5a7c9d12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "youtube_pockettube_channel_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_name", sa.String(length=160), nullable=False),
        sa.Column("channel_id", sa.String(length=100), nullable=False),
        sa.Column("last_hydrated_at", sa.DateTime(timezone=True)),
        sa.Column("catalogue_depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_name", "channel_id", name="uq_pockettube_group_channel"),
    )
    op.create_index(
        "ix_pockettube_channel_group_hydrated",
        "youtube_pockettube_channel_memberships",
        ["group_name", "last_hydrated_at"],
    )
    with op.batch_alter_table("personal_tv_session_items") as batch:
        batch.add_column(
            sa.Column("playhead_seconds", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("personal_tv_session_items") as batch:
        batch.drop_column("playhead_seconds")
    op.drop_index(
        "ix_pockettube_channel_group_hydrated",
        table_name="youtube_pockettube_channel_memberships",
    )
    op.drop_table("youtube_pockettube_channel_memberships")
