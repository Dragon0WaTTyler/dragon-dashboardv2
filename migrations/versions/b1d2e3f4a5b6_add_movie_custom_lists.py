"""add user-owned Movies custom lists

Revision ID: b1d2e3f4a5b6
Revises: a9c4e1f7b2d6
Create Date: 2026-08-26 23:55:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b1d2e3f4a5b6"
down_revision = "a9c4e1f7b2d6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "movie_custom_lists",
        sa.Column("id", sa.String(length=40), primary_key=True, nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_movie_custom_lists_owner_user_id",
        "movie_custom_lists",
        ["owner_user_id"],
    )
    op.create_table(
        "movie_custom_list_items",
        sa.Column("custom_list_id", sa.String(length=40), primary_key=True, nullable=False),
        sa.Column("movie_id", sa.String(length=40), primary_key=True, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["custom_list_id"], ["movie_custom_lists.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_movie_custom_list_items_movie",
        "movie_custom_list_items",
        ["movie_id"],
    )


def downgrade():
    op.drop_index("ix_movie_custom_list_items_movie", table_name="movie_custom_list_items")
    op.drop_table("movie_custom_list_items")
    op.drop_index("ix_movie_custom_lists_owner_user_id", table_name="movie_custom_lists")
    op.drop_table("movie_custom_lists")
