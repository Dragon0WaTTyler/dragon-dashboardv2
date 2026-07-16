"""add TV fetch memory and favorites

Revision ID: a6d9e2f4b8c3
Revises: f5c8a1d3e7b2
Create Date: 2026-07-15 06:20:00.000000
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "a6d9e2f4b8c3"
down_revision = "f5c8a1d3e7b2"
branch_labels = None
depends_on = None


def _preference_key(theme_key: str, tvg_id: str, tvg_name: str, name: str) -> str:
    stable_id = str(tvg_id or "").strip().casefold()
    if stable_id:
        identity = f"tvg-id\x1f{stable_id}"
    else:
        stable_name = str(tvg_name or "").strip() or str(name or "").strip()
        normalized_name = re.sub(r"\s+", " ", stable_name).casefold()
        identity = f"theme\x1f{theme_key}\x1fname\x1f{normalized_name}"
    return hashlib.sha256(identity.encode("utf-8", "ignore")).hexdigest()


def upgrade() -> None:
    op.add_column(
        "tv_playlists",
        sa.Column("imported_sha", sa.String(length=80), nullable=False, server_default=""),
    )
    op.add_column("tv_themes", sa.Column("channel_policy", sa.Boolean(), nullable=True))
    op.add_column(
        "tv_channels", sa.Column("preference_key", sa.String(length=64), nullable=True)
    )
    op.create_table(
        "tv_channel_preferences",
        sa.Column("preference_key", sa.String(length=64), nullable=False),
        sa.Column("theme_key", sa.String(length=240), nullable=False),
        sa.Column("name", sa.String(length=600), nullable=False),
        sa.Column("tvg_id", sa.String(length=300), nullable=False),
        sa.Column("logo_url", sa.String(length=2000), nullable=False),
        sa.Column("enabled_override", sa.Boolean(), nullable=True),
        sa.Column("favorite", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("preference_key"),
    )
    op.create_index(
        "ix_tv_channel_preferences_theme_key",
        "tv_channel_preferences",
        ["theme_key"],
    )
    op.create_index(
        "ix_tv_channel_preferences_favorite",
        "tv_channel_preferences",
        ["favorite"],
    )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE tv_playlists SET imported_sha = source_sha WHERE imported = 1"
        )
    )
    rows = connection.execution_options(stream_results=True).execute(
        sa.text(
            "SELECT c.id, c.tvg_id, c.tvg_name, c.name, c.logo_url, "
            "c.enabled_override, t.key AS theme_key "
            "FROM tv_channels c "
            "JOIN tv_groups g ON g.id = c.group_id "
            "JOIN tv_themes t ON t.id = g.theme_id ORDER BY c.id"
        )
    )
    updates: list[dict[str, int | str]] = []
    preferences: dict[str, dict[str, object]] = {}
    now = datetime.now(UTC)
    for row in rows.mappings():
        key = _preference_key(
            str(row["theme_key"]),
            str(row["tvg_id"] or ""),
            str(row["tvg_name"] or ""),
            str(row["name"] or ""),
        )
        updates.append({"id": int(row["id"]), "preference_key": key})
        if row["enabled_override"] is not None:
            preferences[key] = {
                "preference_key": key,
                "theme_key": str(row["theme_key"]),
                "name": str(row["name"]),
                "tvg_id": str(row["tvg_id"] or ""),
                "logo_url": str(row["logo_url"] or ""),
                "enabled_override": bool(row["enabled_override"]),
                "favorite": False,
                "created_at": now,
                "updated_at": now,
            }
        if len(updates) >= 1000:
            connection.execute(
                sa.text(
                    "UPDATE tv_channels SET preference_key = :preference_key WHERE id = :id"
                ),
                updates,
            )
            updates.clear()
    if updates:
        connection.execute(
            sa.text(
                "UPDATE tv_channels SET preference_key = :preference_key WHERE id = :id"
            ),
            updates,
        )
    if preferences:
        preference_table = sa.table(
            "tv_channel_preferences",
            sa.column("preference_key"),
            sa.column("theme_key"),
            sa.column("name"),
            sa.column("tvg_id"),
            sa.column("logo_url"),
            sa.column("enabled_override"),
            sa.column("favorite"),
            sa.column("created_at"),
            sa.column("updated_at"),
        )
        connection.execute(preference_table.insert(), list(preferences.values()))

    with op.batch_alter_table("tv_channels") as batch_op:
        batch_op.alter_column(
            "preference_key", existing_type=sa.String(length=64), nullable=False
        )
        batch_op.create_index(
            "ix_tv_channels_preference_key", ["preference_key"], unique=False
        )
    with op.batch_alter_table("tv_playlists") as batch_op:
        batch_op.alter_column(
            "imported_sha",
            existing_type=sa.String(length=80),
            nullable=False,
            server_default=None,
        )


def downgrade() -> None:
    with op.batch_alter_table("tv_playlists") as batch_op:
        batch_op.drop_column("imported_sha")
    with op.batch_alter_table("tv_channels") as batch_op:
        batch_op.drop_index("ix_tv_channels_preference_key")
        batch_op.drop_column("preference_key")
    op.drop_column("tv_themes", "channel_policy")
    op.drop_index(
        "ix_tv_channel_preferences_favorite", table_name="tv_channel_preferences"
    )
    op.drop_index(
        "ix_tv_channel_preferences_theme_key", table_name="tv_channel_preferences"
    )
    op.drop_table("tv_channel_preferences")
