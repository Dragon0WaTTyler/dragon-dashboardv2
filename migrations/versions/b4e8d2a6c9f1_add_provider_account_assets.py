"""add provider account asset mirror

Revision ID: b4e8d2a6c9f1
Revises: a7d1e5c3b924
Create Date: 2026-08-11 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "b4e8d2a6c9f1"
down_revision = "a7d1e5c3b924"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playback_provider_account_assets",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("account_key", sa.String(length=80), nullable=False, server_default="default"),
        sa.Column("provider_asset_id", sa.String(length=300), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("folder_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("playable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_status", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider",
            "account_key",
            "provider_asset_id",
            name="uq_playback_provider_account_asset",
        ),
    )
    op.create_index(
        "ix_playback_provider_account_asset_seen",
        "playback_provider_account_assets",
        ["provider", "last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_playback_provider_account_asset_seen",
        table_name="playback_provider_account_assets",
    )
    op.drop_table("playback_provider_account_assets")
