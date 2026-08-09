"""add playback provider foundation

Revision ID: d4a8f2c9e731
Revises: e6b4d2a1c8f7
Create Date: 2026-08-09 00:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "d4a8f2c9e731"
down_revision = "e6b4d2a1c8f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("playback_sources") as batch_op:
        batch_op.add_column(
            sa.Column("provider", sa.String(length=40), nullable=False, server_default="local")
        )
        batch_op.add_column(
            sa.Column("source_type", sa.String(length=40), nullable=False, server_default="local")
        )
        batch_op.add_column(
            sa.Column("provider_asset_id", sa.String(length=300), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("embed_reference", sa.Text(), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("language", sa.String(length=24), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column(
                "subtitle_languages", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
            )
        )
        batch_op.add_column(
            sa.Column("quality", sa.String(length=80), nullable=False, server_default="")
        )
        batch_op.add_column(sa.Column("match_confidence", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column("provenance", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )
        batch_op.add_column(
            sa.Column(
                "authorization_status",
                sa.String(length=40),
                nullable=False,
                server_default="unknown",
            )
        )
        batch_op.add_column(
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(sa.Column("priority_override", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("scope_key", sa.String(length=24), nullable=False, server_default="movie")
        )

    op.execute("UPDATE playback_sources SET provider_asset_id = id WHERE provider_asset_id = ''")
    op.execute(
        "UPDATE playback_sources SET scope_key = "
        "CASE WHEN season IS NOT NULL AND episode IS NOT NULL "
        "THEN printf('s%02de%02d', season, episode) ELSE 'movie' END"
    )

    with op.batch_alter_table("playback_sources") as batch_op:
        batch_op.create_unique_constraint(
            "uq_playback_source_provider_asset",
            ["movie_id", "scope_key", "provider", "provider_asset_id"],
        )
        batch_op.alter_column("provider", server_default=None)
        batch_op.alter_column("source_type", server_default=None)
        batch_op.alter_column("provider_asset_id", server_default=None)
        batch_op.alter_column("embed_reference", server_default=None)
        batch_op.alter_column("language", server_default=None)
        batch_op.alter_column("subtitle_languages", server_default=None)
        batch_op.alter_column("quality", server_default=None)
        batch_op.alter_column("provenance", server_default=None)
        batch_op.alter_column("authorization_status", server_default=None)
        batch_op.alter_column("enabled", server_default=None)
        batch_op.alter_column("scope_key", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("playback_sources") as batch_op:
        batch_op.drop_constraint("uq_playback_source_provider_asset", type_="unique")
        batch_op.drop_column("scope_key")
        batch_op.drop_column("priority_override")
        batch_op.drop_column("enabled")
        batch_op.drop_column("authorization_status")
        batch_op.drop_column("provenance")
        batch_op.drop_column("match_confidence")
        batch_op.drop_column("quality")
        batch_op.drop_column("subtitle_languages")
        batch_op.drop_column("language")
        batch_op.drop_column("embed_reference")
        batch_op.drop_column("provider_asset_id")
        batch_op.drop_column("source_type")
        batch_op.drop_column("provider")
