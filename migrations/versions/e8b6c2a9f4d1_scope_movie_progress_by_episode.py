"""scope movie progress by episode

Revision ID: e8b6c2a9f4d1
Revises: d9a3e5b7c1f6
Create Date: 2026-07-19 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e8b6c2a9f4d1"
down_revision = "d9a3e5b7c1f6"
branch_labels = None
depends_on = None

NAMING_CONVENTION = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade():
    with op.batch_alter_table("movie_progress", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.add_column(sa.Column("season", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("episode", sa.Integer(), nullable=True))
        batch_op.drop_constraint("uq_movie_progress_movie_id", type_="unique")
    op.create_index("ix_movie_progress_scope", "movie_progress", ["movie_id", "season", "episode"])


def downgrade():
    op.drop_index("ix_movie_progress_scope", table_name="movie_progress")
    op.execute("DELETE FROM movie_progress WHERE season IS NOT NULL OR episode IS NOT NULL")
    with op.batch_alter_table("movie_progress", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.create_unique_constraint("uq_movie_progress_movie_id", ["movie_id"])
        batch_op.drop_column("episode")
        batch_op.drop_column("season")
