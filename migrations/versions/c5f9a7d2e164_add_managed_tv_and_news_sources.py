"""add managed tv and news sources

Revision ID: c5f9a7d2e164
Revises: b4e8d2a6c9f1
Create Date: 2026-08-15 03:30:00
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "c5f9a7d2e164"
down_revision = "b4e8d2a6c9f1"
branch_labels = None
depends_on = None


def upgrade():
    sqlite = op.get_bind().dialect.name == "sqlite"
    op.create_table(
        "tv_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("locator", sa.String(2000), nullable=False),
        sa.Column("branch", sa.String(160), nullable=False),
        sa.Column("file_pattern", sa.String(500), nullable=False),
        sa.Column("local_path", sa.String(1000), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("auto_refresh", sa.Boolean(), nullable=False),
        sa.Column("refresh_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("protected", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("last_tested_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tv_sources_source_type", "tv_sources", ["source_type"])
    if sqlite:
        # SQLite batch mode rebuilds the referenced table. On a populated Dragon
        # database that cascades through millions of channel rows and cannot rebuild
        # reading_sources while articles still reference it. ADD COLUMN is safe here;
        # ORM relationships do not require an on-disk FK for this optional owner link.
        op.add_column("tv_playlists", sa.Column("source_id", sa.Integer(), nullable=True))
        op.create_index("ix_tv_playlists_source_id", "tv_playlists", ["source_id"])
        op.add_column(
            "tv_themes",
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        )
    else:
        with op.batch_alter_table("tv_playlists") as batch:
            batch.add_column(sa.Column("source_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_tv_playlists_source_id",
                "tv_sources",
                ["source_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.create_index("ix_tv_playlists_source_id", ["source_id"])
        with op.batch_alter_table("tv_themes") as batch:
            batch.add_column(
                sa.Column("position", sa.Integer(), nullable=False, server_default="0")
            )

    now = datetime.now(UTC)
    sources = sa.table(
        "tv_sources",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("source_type", sa.String),
        sa.column("locator", sa.String),
        sa.column("branch", sa.String),
        sa.column("file_pattern", sa.String),
        sa.column("local_path", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("auto_refresh", sa.Boolean),
        sa.column("refresh_interval_minutes", sa.Integer),
        sa.column("protected", sa.Boolean),
        sa.column("status", sa.String),
        sa.column("last_error", sa.Text),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(
        sources,
        [
            {
                "id": 1,
                "name": "Dragon IPTV catalogue",
                "source_type": "github_repository",
                "locator": "mesbahikarim63-commits/hot-dodo",
                "branch": "main",
                "file_pattern": "*.m3u",
                "local_path": "",
                "enabled": True,
                "auto_refresh": True,
                "refresh_interval_minutes": 360,
                "protected": True,
                "status": "ready",
                "last_error": "",
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    op.execute(sa.text("UPDATE tv_playlists SET source_id = 1 WHERE source_id IS NULL"))

    reading_columns = (
        sa.Column("language", sa.String(12), nullable=False, server_default="auto"),
        sa.Column("auto_refresh", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("refresh_interval_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("maximum_articles", sa.Integer(), nullable=False, server_default="200"),
        sa.Column("download_fulltext", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("download_images", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_tested_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    if sqlite:
        for column in reading_columns:
            op.add_column("reading_sources", column)
    else:
        with op.batch_alter_table("reading_sources") as batch:
            for column in reading_columns:
                batch.add_column(column)
    op.execute(sa.text("UPDATE reading_sources SET created_at = CURRENT_TIMESTAMP"))
    if not sqlite:
        with op.batch_alter_table("reading_sources") as batch:
            batch.alter_column("created_at", nullable=False)


def downgrade():
    sqlite = op.get_bind().dialect.name == "sqlite"
    reading_names = (
        "created_at",
        "last_tested_at",
        "download_images",
        "download_fulltext",
        "maximum_articles",
        "refresh_interval_minutes",
        "auto_refresh",
        "language",
    )
    if sqlite:
        for name in reading_names:
            op.drop_column("reading_sources", name)
        op.drop_column("tv_themes", "position")
        op.drop_index("ix_tv_playlists_source_id", table_name="tv_playlists")
        op.drop_column("tv_playlists", "source_id")
    else:
        with op.batch_alter_table("reading_sources") as batch:
            for name in reading_names:
                batch.drop_column(name)
        with op.batch_alter_table("tv_themes") as batch:
            batch.drop_column("position")
        with op.batch_alter_table("tv_playlists") as batch:
            batch.drop_index("ix_tv_playlists_source_id")
            batch.drop_constraint("fk_tv_playlists_source_id", type_="foreignkey")
            batch.drop_column("source_id")
    op.drop_index("ix_tv_sources_source_type", table_name="tv_sources")
    op.drop_table("tv_sources")
