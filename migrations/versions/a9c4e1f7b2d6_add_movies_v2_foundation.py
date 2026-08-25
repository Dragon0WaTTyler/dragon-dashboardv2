"""add Movies V2 personal-state foundation

Revision ID: a9c4e1f7b2d6
Revises: fe6a0b2c3d4e
Create Date: 2026-08-25 23:30:00.000000
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "a9c4e1f7b2d6"
down_revision = "fe6a0b2c3d4e"
branch_labels = None
depends_on = None


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _media_key(row: sa.RowMapping) -> str:
    media_type = "tv" if str(row["media_type"] or "").lower() == "tv" else "movie"
    tmdb_id = str(_mapping(row["external_ids"]).get("tmdb_id") or "").strip()
    if tmdb_id.isdigit() and int(tmdb_id) > 0:
        return f"{media_type}:{int(tmdb_id)}"
    return f"local:{media_type}:{row['id']}"


def _lifecycle(status: Any) -> str:
    value = str(status or "").strip().lower()
    if value in {"finished", "watched"}:
        return "watched"
    if value == "watching":
        return "watching"
    return "want_to_watch"


def _scope_key(row: sa.RowMapping) -> str:
    season, episode = row["season"], row["episode"]
    if season is None and episode is None:
        return "movie"
    if season is None or episode is None:
        raise RuntimeError(
            "Movies V2 migration found malformed progress scope: season and episode "
            "must either both be set or both be null."
        )
    season_number, episode_number = int(season), int(episode)
    if season_number < 0 or episode_number < 1:
        raise RuntimeError("Movies V2 migration found an invalid episode progress scope.")
    return f"s{season_number:02d}e{episode_number:02d}"


def _timestamp(row: sa.RowMapping) -> datetime:
    value = row["client_updated_at"] or row["updated_at"]
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=UTC)


def upgrade():
    bind = op.get_bind()

    op.add_column("movies", sa.Column("media_key", sa.String(length=96), nullable=True))
    movie_rows = list(
        bind.execute(
            sa.text(
                "SELECT id, media_type, external_ids, status, personal_score, metadata_state, "
                "created_at, updated_at FROM movies"
            )
        ).mappings()
    )
    seen_keys: set[str] = set()
    for row in movie_rows:
        media_key = _media_key(row)
        if media_key in seen_keys:
            raise RuntimeError(
                "Movies V2 migration found duplicate typed TMDB identity. Stop and reconcile "
                "those Movie records before applying the canonical key invariant."
            )
        seen_keys.add(media_key)
        bind.execute(
            sa.text("UPDATE movies SET media_key = :media_key WHERE id = :movie_id"),
            {"media_key": media_key, "movie_id": row["id"]},
        )
    op.create_index("ix_movies_media_key", "movies", ["media_key"], unique=True)
    # SQLite rebuilds a referenced table to alter nullability, which cascades
    # into every child table under this application's foreign-key settings.
    # Keep the add-column operation non-destructive and enforce the same
    # invariant with triggers instead.
    op.execute(
        "CREATE TRIGGER trg_movies_media_key_insert "
        "BEFORE INSERT ON movies "
        "WHEN NEW.media_key IS NULL OR trim(NEW.media_key) = '' "
        "BEGIN SELECT RAISE(ABORT, 'movies.media_key is required'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_movies_media_key_update "
        "BEFORE UPDATE OF media_key ON movies "
        "WHEN NEW.media_key IS NULL OR trim(NEW.media_key) = '' "
        "BEGIN SELECT RAISE(ABORT, 'movies.media_key is required'); END"
    )

    op.create_table(
        "movie_library_entries",
        sa.Column("media_key", sa.String(length=96), primary_key=True, nullable=False),
        sa.Column("movie_id", sa.String(length=40), nullable=False, unique=True),
        sa.Column("lifecycle_status", sa.String(length=30), nullable=False),
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("personal_rating", sa.Float(), nullable=True),
        sa.Column("personal_label", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_watched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_watched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manual_lifecycle_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["media_key"], ["movies.media_key"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_movie_library_entries_lifecycle_status",
        "movie_library_entries",
        ["lifecycle_status"],
    )

    latest_progress_by_movie: dict[str, datetime] = {}
    for progress_row in bind.execute(
        sa.text("SELECT movie_id, client_updated_at, updated_at FROM movie_progress")
    ).mappings():
        movie_id = str(progress_row["movie_id"])
        candidate = _timestamp(progress_row)
        current = latest_progress_by_movie.get(movie_id)
        if current is None or candidate > current:
            latest_progress_by_movie[movie_id] = candidate
    for row in movie_rows:
        metadata = _mapping(row["metadata_state"])
        lifecycle = _lifecycle(row["status"])
        last_watched_at = latest_progress_by_movie.get(row["id"])
        if last_watched_at == datetime.min.replace(tzinfo=UTC):
            last_watched_at = None
        completed_at = last_watched_at if lifecycle == "watched" else None
        bind.execute(
            sa.text(
                "INSERT INTO movie_library_entries ("
                "media_key, movie_id, lifecycle_status, is_favorite, personal_rating, "
                "personal_label, added_at, first_watched_at, last_watched_at, completed_at, "
                "manual_lifecycle_at, created_at, updated_at"
                ") VALUES ("
                ":media_key, :movie_id, :lifecycle_status, 0, :personal_rating, "
                ":personal_label, :added_at, NULL, :last_watched_at, :completed_at, NULL, "
                ":created_at, :updated_at"
                ")"
            ),
            {
                "media_key": _media_key(row),
                "movie_id": row["id"],
                "lifecycle_status": lifecycle,
                "personal_rating": row["personal_score"],
                "personal_label": str(metadata.get("personal_score_label") or "")[:160],
                "added_at": row["created_at"],
                "last_watched_at": last_watched_at,
                "completed_at": completed_at,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )

    op.create_table(
        "movie_progress_duplicate_archive",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("migration_revision", sa.String(length=32), nullable=False),
        sa.Column("original_progress_id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.String(length=40), nullable=False),
        sa.Column("scope_key", sa.String(length=24), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_movie_progress_duplicate_archive_scope",
        "movie_progress_duplicate_archive",
        ["movie_id", "scope_key"],
    )

    op.add_column("movie_progress", sa.Column("scope_key", sa.String(length=24), nullable=True))
    progress_rows = list(
        bind.execute(
            sa.text(
                "SELECT id, movie_id, season, episode, current_seconds, duration_seconds, "
                "completed, "
                "client_updated_at, updated_at FROM movie_progress"
            )
        ).mappings()
    )
    grouped: dict[tuple[str, str], list[sa.RowMapping]] = defaultdict(list)
    for row in progress_rows:
        grouped[(str(row["movie_id"]), _scope_key(row))].append(row)

    archived_at = datetime.now(UTC)
    for (movie_id, scope_key), rows in grouped.items():
        ordered = sorted(rows, key=lambda row: (_timestamp(row), int(row["id"])), reverse=True)
        winner = ordered[0]
        if not bool(winner["completed"]) and any(bool(row["completed"]) for row in ordered[1:]):
            raise RuntimeError(
                "Movies V2 migration found ambiguous duplicate progress where a newer incomplete "
                "row would supersede a completed row. Inspect and reconcile those rows first."
            )
        bind.execute(
            sa.text("UPDATE movie_progress SET scope_key = :scope_key WHERE id = :progress_id"),
            {"scope_key": scope_key, "progress_id": winner["id"]},
        )
        for discarded in ordered[1:]:
            payload = {
                key: discarded[key]
                for key in (
                    "id",
                    "movie_id",
                    "season",
                    "episode",
                    "current_seconds",
                    "duration_seconds",
                    "completed",
                    "client_updated_at",
                    "updated_at",
                )
            }
            bind.execute(
                sa.text(
                    "INSERT INTO movie_progress_duplicate_archive ("
                    "migration_revision, original_progress_id, movie_id, scope_key, payload_json, "
                    "archived_at"
                    ") VALUES ("
                    ":migration_revision, :original_progress_id, :movie_id, :scope_key, "
                    ":payload_json, :archived_at"
                    ")"
                ),
                {
                    "migration_revision": revision,
                    "original_progress_id": discarded["id"],
                    "movie_id": movie_id,
                    "scope_key": scope_key,
                    "payload_json": json.dumps(payload, default=str),
                    "archived_at": archived_at,
                },
            )
            bind.execute(
                sa.text("DELETE FROM movie_progress WHERE id = :progress_id"),
                {"progress_id": discarded["id"]},
            )

    op.drop_index("ix_movie_progress_scope", table_name="movie_progress")
    with op.batch_alter_table("movie_progress") as batch_op:
        batch_op.alter_column("scope_key", existing_type=sa.String(length=24), nullable=False)
        batch_op.create_unique_constraint("uq_movie_progress_scope", ["movie_id", "scope_key"])
    op.create_index("ix_movie_progress_scope", "movie_progress", ["movie_id", "scope_key"])


def downgrade():
    op.drop_index("ix_movie_progress_scope", table_name="movie_progress")
    with op.batch_alter_table("movie_progress") as batch_op:
        batch_op.drop_constraint("uq_movie_progress_scope", type_="unique")
        batch_op.drop_column("scope_key")
    op.create_index("ix_movie_progress_scope", "movie_progress", ["movie_id", "season", "episode"])
    op.drop_index(
        "ix_movie_progress_duplicate_archive_scope",
        table_name="movie_progress_duplicate_archive",
    )
    op.drop_table("movie_progress_duplicate_archive")
    op.drop_index("ix_movie_library_entries_lifecycle_status", table_name="movie_library_entries")
    op.drop_table("movie_library_entries")
    op.execute("DROP TRIGGER trg_movies_media_key_update")
    op.execute("DROP TRIGGER trg_movies_media_key_insert")
    op.drop_index("ix_movies_media_key", table_name="movies")
    # Keep the formerly required column during downgrade. Dropping it would
    # again rebuild the referenced SQLite table and cascade-delete playback and
    # progress rows. Older application code ignores this additive column.
