"""add training learning and history

Revision ID: 93bfe4d276a0
Revises: 7d4a9c2e61f3
Create Date: 2026-07-14 04:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "93bfe4d276a0"
down_revision = "7d4a9c2e61f3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "history_events",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("domain", sa.String(40), nullable=False),
        sa.Column("entity_type", sa.String(60), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("label", sa.String(500), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_history_domain_created", "history_events", ["domain", "created_at"])
    op.create_table(
        "chess_games",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("external_id", sa.String(120), nullable=False, unique=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("white", sa.String(180), nullable=False),
        sa.Column("black", sa.String(180), nullable=False),
        sa.Column("user_color", sa.String(20), nullable=False),
        sa.Column("user_result", sa.String(20), nullable=False),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("played_at", sa.DateTime(timezone=True)),
        sa.Column("time_class", sa.String(40), nullable=False),
        sa.Column("time_control", sa.String(60), nullable=False),
        sa.Column("opening", sa.JSON(), nullable=False),
        sa.Column("pgn", sa.Text(), nullable=False),
        sa.Column("moves", sa.JSON(), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("rated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chess_games_source", "chess_games", ["source"])
    op.create_table(
        "chess_puzzles",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("external_id", sa.String(120), nullable=False, unique=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("fen", sa.String(200), nullable=False),
        sa.Column("moves", sa.JSON(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("themes", sa.JSON(), nullable=False),
        sa.Column("opening_tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "puzzle_attempts",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("puzzle_id", sa.String(40), sa.ForeignKey("chess_puzzles.id", ondelete="CASCADE")),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("wrong_count", sa.Integer(), nullable=False),
        sa.Column("reveal_used", sa.Boolean(), nullable=False),
        sa.Column("completed_clean", sa.Boolean(), nullable=False),
        sa.Column("needs_repeat", sa.Boolean(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "chess_courses",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("level", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("lines", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "german_resources",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("title", sa.String(400), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "german_vocabulary",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("term", sa.String(240), nullable=False),
        sa.Column("meaning", sa.String(500), nullable=False),
        sa.Column("example", sa.Text(), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("german_vocabulary")
    op.drop_table("german_resources")
    op.drop_table("chess_courses")
    op.drop_table("puzzle_attempts")
    op.drop_table("chess_puzzles")
    op.drop_index("ix_chess_games_source", table_name="chess_games")
    op.drop_table("chess_games")
    op.drop_index("ix_history_domain_created", table_name="history_events")
    op.drop_table("history_events")
