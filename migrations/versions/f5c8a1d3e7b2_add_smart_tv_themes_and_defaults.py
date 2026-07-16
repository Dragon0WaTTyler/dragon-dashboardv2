"""add smart TV themes and off-by-default sources

Revision ID: f5c8a1d3e7b2
Revises: e4b7d2c9a6f1
Create Date: 2026-07-15 05:10:00.000000
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

import sqlalchemy as sa
from alembic import op

revision = "f5c8a1d3e7b2"
down_revision = "e4b7d2c9a6f1"
branch_labels = None
depends_on = None

UMBRELLA_PREFIXES = {"afr", "arab", "asia", "euro", "lame", "name"}
TOKEN_ALIASES = {
    "de": "germany",
    "deutschland": "germany",
    "espana": "spain",
    "fr": "france",
    "franch": "france",
    "it": "italy",
    "italia": "italy",
    "nl": "netherlands",
    "pt": "portugal",
}
PHRASE_ALIASES = {
    "united arab emirates": "uae",
    "united kingdom": "uk",
    "united states": "usa",
}


def _identity(group_name: str) -> tuple[str, str]:
    display = re.sub(r"\s+", " ", str(group_name or "Ungrouped")).strip()
    display = re.sub(r"\s*[|:»›]+\s*", " · ", display).strip(" ·-") or "Ungrouped"
    folded = unicodedata.normalize("NFKD", display.casefold()).encode(
        "ascii", "ignore"
    ).decode("ascii")
    for phrase, replacement in PHRASE_ALIASES.items():
        folded = folded.replace(phrase, replacement)
    tokens = re.findall(r"[a-z0-9]+", folded)
    if len(tokens) > 1 and tokens[0] in UMBRELLA_PREFIXES:
        tokens.pop(0)
    normalized = [TOKEN_ALIASES.get(token, token) for token in tokens]
    deduplicated: list[str] = []
    for token in normalized:
        if not deduplicated or deduplicated[-1] != token:
            deduplicated.append(token)
    key = "-".join(deduplicated) or "ungrouped"
    if len(key) > 220:
        key = f"{key[:200]}-{hashlib.sha256(key.encode()).hexdigest()[:16]}"
    return key, display


def upgrade() -> None:
    op.create_table(
        "tv_themes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=240), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("channel_count", sa.Integer(), nullable=False),
        sa.Column("group_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index("ix_tv_themes_enabled_name", "tv_themes", ["enabled", "name"])
    op.add_column("tv_groups", sa.Column("theme_id", sa.Integer(), nullable=True))

    connection = op.get_bind()
    groups = connection.execute(
        sa.text("SELECT id, name, enabled, channel_count FROM tv_groups ORDER BY id")
    ).mappings()
    themes: dict[str, dict[str, int | str | bool]] = {}
    group_keys: list[tuple[int, str]] = []
    for group in groups:
        key, name = _identity(str(group["name"]))
        group_keys.append((int(group["id"]), key))
        theme = themes.setdefault(
            key,
            {
                "name": name,
                "enabled": False,
                "channel_count": 0,
                "group_count": 0,
            },
        )
        theme["enabled"] = bool(theme["enabled"]) or bool(group["enabled"])
        theme["channel_count"] = int(theme["channel_count"]) + int(
            group["channel_count"] or 0
        )
        theme["group_count"] = int(theme["group_count"]) + 1

    theme_ids: dict[str, int] = {}
    for key, theme in themes.items():
        result = connection.execute(
            sa.text(
                "INSERT INTO tv_themes "
                "(key, name, enabled, channel_count, group_count) "
                "VALUES (:key, :name, :enabled, :channel_count, :group_count)"
            ),
            {"key": key, **theme},
        )
        theme_ids[key] = int(result.lastrowid)
    for group_id, key in group_keys:
        connection.execute(
            sa.text("UPDATE tv_groups SET theme_id = :theme_id, enabled = 0 WHERE id = :id"),
            {"theme_id": theme_ids[key], "id": group_id},
        )

    connection.execute(sa.text("UPDATE tv_playlists SET enabled = 0"))
    with op.batch_alter_table("tv_groups") as batch_op:
        batch_op.alter_column("theme_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_tv_groups_theme_id_tv_themes",
            "tv_themes",
            ["theme_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index("ix_tv_groups_theme_id", ["theme_id"], unique=False)
        batch_op.create_index(
            "ix_tv_groups_theme_playlist", ["theme_id", "playlist_id"], unique=False
        )
    op.create_index(
        "ix_tv_playlists_tv_active",
        "tv_playlists",
        ["enabled", "imported", "available"],
    )
    op.create_index(
        "ix_tv_channels_enabled_override", "tv_channels", ["enabled_override"]
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE tv_groups SET enabled = COALESCE((SELECT enabled FROM tv_themes "
            "WHERE tv_themes.id = tv_groups.theme_id), 0)"
        )
    )
    op.drop_index("ix_tv_channels_enabled_override", table_name="tv_channels")
    op.drop_index("ix_tv_playlists_tv_active", table_name="tv_playlists")
    with op.batch_alter_table("tv_groups") as batch_op:
        batch_op.drop_index("ix_tv_groups_theme_playlist")
        batch_op.drop_index("ix_tv_groups_theme_id")
        batch_op.drop_constraint("fk_tv_groups_theme_id_tv_themes", type_="foreignkey")
        batch_op.drop_column("theme_id")
    op.drop_index("ix_tv_themes_enabled_name", table_name="tv_themes")
    op.drop_table("tv_themes")
