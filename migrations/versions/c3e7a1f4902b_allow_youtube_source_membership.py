"""allow a YouTube video to belong to more than one source

Revision ID: c3e7a1f4902b
Revises: af6c42e9b831
Create Date: 2026-07-14 03:15:00
"""

import sqlalchemy as sa
from alembic import op

revision = "c3e7a1f4902b"
down_revision = "af6c42e9b831"
branch_labels = None
depends_on = None


def _create_table(name: str, *, source_scoped: bool) -> None:
    constraints = [sa.PrimaryKeyConstraint("id")]
    if source_scoped:
        constraints.append(
            sa.UniqueConstraint(
                "source", "external_id", name="uq_youtube_source_external_id"
            )
        )
    else:
        constraints.append(sa.UniqueConstraint("external_id"))
    op.create_table(
        name,
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("external_id", sa.String(length=80), nullable=False),
        sa.Column("playlist_item_id", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("group_name", sa.String(length=160), nullable=False),
        sa.Column("channel_id", sa.String(length=100), nullable=False),
        sa.Column("channel_title", sa.String(length=240), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.String(length=1000), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("watched", sa.Boolean(), nullable=False),
        sa.Column("removed_from_source", sa.Boolean(), nullable=False),
        sa.Column("local_history", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        *constraints,
    )


def _copy_rows(source: str, target: str) -> None:
    columns = (
        "id, external_id, playlist_item_id, source, group_name, channel_id, "
        "channel_title, title, description, thumbnail_url, published_at, "
        "duration_seconds, position, watched, removed_from_source, local_history, "
        "created_at, updated_at"
    )
    op.execute(sa.text(f"INSERT INTO {target} ({columns}) SELECT {columns} FROM {source}"))


def _create_indexes() -> None:
    op.create_index("ix_youtube_videos_source", "youtube_videos", ["source"])
    op.create_index("ix_youtube_videos_watched", "youtube_videos", ["watched"])
    op.create_index("ix_youtube_source_position", "youtube_videos", ["source", "position"])
    op.create_index(
        "ix_youtube_group_channel", "youtube_videos", ["group_name", "channel_title"]
    )


def upgrade():
    _create_table("youtube_videos_scoped", source_scoped=True)
    _copy_rows("youtube_videos", "youtube_videos_scoped")
    op.drop_table("youtube_videos")
    op.rename_table("youtube_videos_scoped", "youtube_videos")
    _create_indexes()


def downgrade():
    duplicate_count = op.get_bind().scalar(
        sa.text(
            "SELECT COUNT(*) FROM ("
            "SELECT external_id FROM youtube_videos GROUP BY external_id HAVING COUNT(*) > 1"
            ")"
        )
    )
    if duplicate_count:
        raise RuntimeError(
            "Cannot restore global YouTube IDs while videos belong to multiple sources."
        )
    _create_table("youtube_videos_global", source_scoped=False)
    _copy_rows("youtube_videos", "youtube_videos_global")
    op.drop_table("youtube_videos")
    op.rename_table("youtube_videos_global", "youtube_videos")
    _create_indexes()
