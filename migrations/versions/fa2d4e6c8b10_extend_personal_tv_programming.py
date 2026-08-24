"""extend personal television programming

Revision ID: fa2d4e6c8b10
Revises: f9c1d2e3a4b5
Create Date: 2026-08-23 13:00:00
"""

import sqlalchemy as sa
from alembic import op


revision = "fa2d4e6c8b10"
down_revision = "f9c1d2e3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("personal_tv_preferences") as batch:
        batch.add_column(sa.Column("preferred_topics", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("preferred_formats", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("preferred_languages", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("preferred_creators", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("blocked_creators", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("avoided_keywords", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(
            sa.Column("discovery_level", sa.String(length=20), nullable=False, server_default="balanced")
        )
        batch.add_column(sa.Column("source_quality", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("daypart_profiles", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    with op.batch_alter_table("personal_tv_sessions") as batch:
        batch.add_column(sa.Column("request_intent", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("ending_reason", sa.String(length=80), nullable=False, server_default=""))
        batch.create_index("ix_personal_tv_sessions_expires_at", ["expires_at"])
    with op.batch_alter_table("personal_tv_session_items") as batch:
        batch.add_column(
            sa.Column("content_type", sa.String(length=40), nullable=False, server_default="video")
        )
        batch.add_column(sa.Column("language", sa.String(length=24), nullable=False, server_default=""))
        batch.add_column(sa.Column("program_role", sa.String(length=40), nullable=False, server_default=""))
        batch.add_column(sa.Column("story_key", sa.String(length=160), nullable=False, server_default=""))
    op.create_table(
        "personal_tv_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=40)),
        sa.Column("session_item_id", sa.Integer()),
        sa.Column("candidate_id", sa.String(length=80), nullable=False),
        sa.Column("creator", sa.String(length=240), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["personal_tv_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_item_id"], ["personal_tv_session_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_personal_tv_feedback_kind_created",
        "personal_tv_feedback",
        ["kind", "created_at"],
    )
    op.create_index("ix_personal_tv_feedback_session_id", "personal_tv_feedback", ["session_id"])
    op.create_index("ix_personal_tv_feedback_session_item_id", "personal_tv_feedback", ["session_item_id"])
    op.create_index("ix_personal_tv_feedback_candidate_id", "personal_tv_feedback", ["candidate_id"])
    op.create_index("ix_personal_tv_feedback_creator", "personal_tv_feedback", ["creator"])
    op.create_table(
        "personal_tv_prepared_programs",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("session_id", sa.String(length=40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["personal_tv_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_personal_tv_prepared_programs_start",
        "personal_tv_prepared_programs",
        ["starts_at", "state"],
    )


def downgrade() -> None:
    op.drop_index("ix_personal_tv_prepared_programs_start", table_name="personal_tv_prepared_programs")
    op.drop_table("personal_tv_prepared_programs")
    for index in (
        "ix_personal_tv_feedback_creator",
        "ix_personal_tv_feedback_candidate_id",
        "ix_personal_tv_feedback_session_item_id",
        "ix_personal_tv_feedback_session_id",
        "ix_personal_tv_feedback_kind_created",
    ):
        op.drop_index(index, table_name="personal_tv_feedback")
    op.drop_table("personal_tv_feedback")
    with op.batch_alter_table("personal_tv_session_items") as batch:
        batch.drop_column("story_key")
        batch.drop_column("program_role")
        batch.drop_column("language")
        batch.drop_column("content_type")
    with op.batch_alter_table("personal_tv_sessions") as batch:
        batch.drop_index("ix_personal_tv_sessions_expires_at")
        batch.drop_column("ending_reason")
        batch.drop_column("expires_at")
        batch.drop_column("request_intent")
    with op.batch_alter_table("personal_tv_preferences") as batch:
        for column in (
            "enabled",
            "daypart_profiles",
            "source_quality",
            "discovery_level",
            "avoided_keywords",
            "blocked_creators",
            "preferred_creators",
            "preferred_languages",
            "preferred_formats",
            "preferred_topics",
        ):
            batch.drop_column(column)
