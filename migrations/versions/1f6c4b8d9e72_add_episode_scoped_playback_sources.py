"""add episode-scoped playback sources

Revision ID: 1f6c4b8d9e72
Revises: b86bbec3d904
Create Date: 2026-07-25 23:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "1f6c4b8d9e72"
down_revision = "f2a4d8c9e731"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("playback_sources") as batch_op:
        batch_op.add_column(sa.Column("season", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("episode", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("source_role", sa.String(length=40), nullable=False, server_default="")
        )

    op.execute(
        """
        UPDATE playback_sources
        SET season = json_extract(metadata_json, '$.season')
        WHERE json_extract(metadata_json, '$.season') IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE playback_sources
        SET episode = json_extract(metadata_json, '$.episode')
        WHERE json_extract(metadata_json, '$.episode') IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE playback_sources
        SET source_role = CASE
            WHEN json_extract(metadata_json, '$.release_mode') = 'season_pack'
              OR json_extract(metadata_json, '$.season_pack') = 1
            THEN 'season_pack_fallback'
            WHEN season IS NOT NULL AND episode IS NOT NULL
            THEN 'exact_episode'
            ELSE ''
        END
        """
    )

    with op.batch_alter_table("playback_sources") as batch_op:
        batch_op.alter_column("source_role", server_default=None)


def downgrade():
    with op.batch_alter_table("playback_sources") as batch_op:
        batch_op.drop_column("source_role")
        batch_op.drop_column("episode")
        batch_op.drop_column("season")
