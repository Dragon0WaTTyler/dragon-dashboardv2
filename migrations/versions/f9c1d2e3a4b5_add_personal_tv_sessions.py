"""add personal television programming sessions

Revision ID: f9c1d2e3a4b5
Revises: f8a1b2c3d4e5
Create Date: 2026-08-23 12:00:00
"""

import sqlalchemy as sa
from alembic import op


revision = "f9c1d2e3a4b5"
down_revision = "f8a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "personal_tv_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("default_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("selected_groups", sa.JSON(), nullable=False),
        sa.Column("avoid_watched", sa.Boolean(), nullable=False),
        sa.Column("no_shorts", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "personal_tv_sessions",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("requested_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("request_groups", sa.JSON(), nullable=False),
        sa.Column("avoid_watched", sa.Boolean(), nullable=False),
        sa.Column("no_shorts", sa.Boolean(), nullable=False),
        sa.Column("programming_version", sa.String(length=40), nullable=False),
        sa.Column("current_item_index", sa.Integer(), nullable=False),
        sa.Column("elapsed_seconds", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_tv_sessions_state_updated", "personal_tv_sessions", ["state", "updated_at"])
    op.create_table(
        "personal_tv_session_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=40), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("candidate_id", sa.String(length=80), nullable=False),
        sa.Column("content_id", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("creator", sa.String(length=240), nullable=False),
        sa.Column("thumbnail_url", sa.String(length=1000), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("planned_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("reason_selected", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("completion_ratio", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("skip_reason", sa.String(length=100), nullable=False),
        sa.Column("replaced_item_id", sa.Integer()),
        sa.ForeignKeyConstraint(["session_id"], ["personal_tv_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_tv_session_items_session_position", "personal_tv_session_items", ["session_id", "position"])
    op.create_index("ix_personal_tv_session_items_session_id", "personal_tv_session_items", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_personal_tv_session_items_session_id", table_name="personal_tv_session_items")
    op.drop_index("ix_personal_tv_session_items_session_position", table_name="personal_tv_session_items")
    op.drop_table("personal_tv_session_items")
    op.drop_index("ix_personal_tv_sessions_state_updated", table_name="personal_tv_sessions")
    op.drop_table("personal_tv_sessions")
    op.drop_table("personal_tv_preferences")
