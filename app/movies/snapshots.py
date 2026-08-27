"""Portable, versioned Movies personal-state snapshots.

This module deliberately owns only canonical Movies memory. Playback sources,
runtime state, credentials, and disposable metadata caches have no place here.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

UTC = getattr(datetime, "UTC", timezone.utc)

from sqlalchemy.orm import selectinload

from app.extensions import db
from app.movies.models import (
    Movie,
    MovieCustomList,
    MovieCustomListItem,
    MovieLibraryEntry,
    MovieProgress,
    progress_scope_key,
)
from app.shared.time import utc_now

UTC = timezone.utc  # noqa: UP017 - keep Python 3.10 compatibility

MOVIES_SNAPSHOT_SCHEMA_VERSION = 1
_SUPPORTED_SCHEMA_VERSIONS = {0, MOVIES_SNAPSHOT_SCHEMA_VERSION}
_LIFECYCLE_STATUSES = {"want_to_watch", "watching", "watched"}
_MEDIA_KEY_PATTERN = re.compile(r"(?:movie|tv):\d+|local:(?:movie|tv):[A-Za-z0-9_-]+")
_LIST_KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,40}")


class MoviesSnapshotValidationError(ValueError):
    """A supplied snapshot is not safe to preview or apply."""


class MoviesSnapshotConflictError(ValueError):
    """A valid snapshot conflicts with another local owner's list."""


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _timestamp(value: Any, field: str) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise MoviesSnapshotValidationError(f"{field} must include a UTC offset.")
        return value.astimezone(UTC)
    if not isinstance(value, str):
        raise MoviesSnapshotValidationError(f"{field} must be an ISO-8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MoviesSnapshotValidationError(f"{field} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise MoviesSnapshotValidationError(f"{field} must include a UTC offset.")
    return parsed.astimezone(UTC)


def _bounded_text(value: Any, field: str, *, limit: int, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise MoviesSnapshotValidationError(f"{field} must be text.")
    normalized = value.strip()
    if required and not normalized:
        raise MoviesSnapshotValidationError(f"{field} is required.")
    if len(normalized) > limit:
        raise MoviesSnapshotValidationError(f"{field} is too long.")
    return normalized


def _integer(value: Any, field: str, *, minimum: int = 0, maximum: int = 2_147_483_647) -> int:
    if isinstance(value, bool):
        raise MoviesSnapshotValidationError(f"{field} must be an integer.")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise MoviesSnapshotValidationError(f"{field} must be an integer.") from exc
    if not minimum <= result <= maximum:
        raise MoviesSnapshotValidationError(f"{field} is outside its supported range.")
    return result


def _optional_rating(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise MoviesSnapshotValidationError("personal_rating must be numeric.")
    try:
        rating = float(value)
    except (TypeError, ValueError) as exc:
        raise MoviesSnapshotValidationError("personal_rating must be numeric.") from exc
    if not 0 <= rating <= 5:
        raise MoviesSnapshotValidationError("personal_rating must be between 0 and 5.")
    return rating


def _safe_external_ids(value: Any, media_type: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise MoviesSnapshotValidationError("media.external_ids must be an object.")
    result: dict[str, str] = {}
    tmdb_id = str(value.get("tmdb_id") or "").strip()
    if tmdb_id:
        if not tmdb_id.isdigit() or int(tmdb_id) <= 0:
            raise MoviesSnapshotValidationError("media.external_ids.tmdb_id is invalid.")
        result["tmdb_id"] = str(int(tmdb_id))
        result["tmdb_type"] = media_type
    imdb_id = str(value.get("imdb_id") or "").strip()
    if imdb_id:
        if not re.fullmatch(r"tt\d{4,16}", imdb_id):
            raise MoviesSnapshotValidationError("media.external_ids.imdb_id is invalid.")
        result["imdb_id"] = imdb_id
    return result


def _media_type_for_key(media_key: str) -> str:
    if media_key.startswith("movie:") or media_key.startswith("local:movie:"):
        return "movie"
    if media_key.startswith("tv:") or media_key.startswith("local:tv:"):
        return "tv"
    raise MoviesSnapshotValidationError("media_key must be a typed Dragon media key.")


def _normalize_preferences(value: Any) -> dict[str, Any]:
    defaults = {
        "autoplay_next": True,
        "automatic_resume": True,
        "default_subtitle_language": "",
        "preferred_source": "",
        "preferred_region": "US",
        "reduced_effects": False,
        "ambient_level": "subtle",
    }
    if value is None:
        return defaults
    if not isinstance(value, Mapping):
        raise MoviesSnapshotValidationError("preferences must be an object.")
    for key in ("autoplay_next", "automatic_resume", "reduced_effects"):
        if key in value:
            if not isinstance(value[key], bool):
                raise MoviesSnapshotValidationError(f"preferences.{key} must be boolean.")
            defaults[key] = value[key]
    language = _bounded_text(
        value.get("default_subtitle_language", ""),
        "preferences.default_subtitle_language",
        limit=3,
    ).lower()
    if language and not re.fullmatch(r"[a-z]{2,3}", language):
        raise MoviesSnapshotValidationError("preferences.default_subtitle_language is invalid.")
    defaults["default_subtitle_language"] = language
    source = _bounded_text(
        value.get("preferred_source", ""), "preferences.preferred_source", limit=40
    ).lower()
    if source and not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", source):
        raise MoviesSnapshotValidationError("preferences.preferred_source is invalid.")
    defaults["preferred_source"] = source
    region = _bounded_text(
        value.get("preferred_region", "US"), "preferences.preferred_region", limit=2
    ).upper()
    if not re.fullmatch(r"[A-Z]{2}", region):
        raise MoviesSnapshotValidationError("preferences.preferred_region is invalid.")
    defaults["preferred_region"] = region
    ambient = value.get("ambient_level", "subtle")
    if ambient not in {"off", "subtle", "normal", "vivid"}:
        raise MoviesSnapshotValidationError("preferences.ambient_level is invalid.")
    defaults["ambient_level"] = ambient
    return defaults


def validate_movies_snapshot(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize an untrusted snapshot without changing local state."""

    if not isinstance(payload, Mapping):
        raise MoviesSnapshotValidationError("Movies snapshot must be an object.")
    version = payload.get("schema_version", 0)
    version = _integer(version, "schema_version", minimum=0, maximum=999)
    if version not in _SUPPORTED_SCHEMA_VERSIONS:
        raise MoviesSnapshotValidationError("This Movies snapshot schema version is unsupported.")
    media_rows = payload.get("media")
    library_rows = payload.get("library_entries")
    progress_rows = payload.get("progress", [])
    list_rows = payload.get("custom_lists", [])
    if not isinstance(media_rows, list) or not isinstance(library_rows, list):
        raise MoviesSnapshotValidationError("media and library_entries must be arrays.")
    if not isinstance(progress_rows, list) or not isinstance(list_rows, list):
        raise MoviesSnapshotValidationError("progress and custom_lists must be arrays.")

    media: list[dict[str, Any]] = []
    media_keys: set[str] = set()
    for index, raw in enumerate(media_rows):
        if not isinstance(raw, Mapping):
            raise MoviesSnapshotValidationError(f"media[{index}] must be an object.")
        media_key = _bounded_text(
            raw.get("media_key"), f"media[{index}].media_key", limit=96, required=True
        )
        if not _MEDIA_KEY_PATTERN.fullmatch(media_key) or media_key in media_keys:
            raise MoviesSnapshotValidationError(
                f"media[{index}].media_key is invalid or duplicated."
            )
        media_type = _bounded_text(
            raw.get("media_type"), f"media[{index}].media_type", limit=20, required=True
        ).lower()
        if media_type not in {"movie", "tv"} or media_type != _media_type_for_key(media_key):
            raise MoviesSnapshotValidationError(f"media[{index}] has a mismatched media type.")
        year = raw.get("year")
        media.append(
            {
                "media_key": media_key,
                "media_type": media_type,
                "title": _bounded_text(
                    raw.get("title"), f"media[{index}].title", limit=300, required=True
                ),
                "original_title": _bounded_text(
                    raw.get("original_title"), f"media[{index}].original_title", limit=300
                ),
                "year": None
                if year is None
                else _integer(year, f"media[{index}].year", minimum=1800, maximum=2200),
                "external_ids": _safe_external_ids(raw.get("external_ids"), media_type),
            }
        )
        media_keys.add(media_key)

    library_entries: list[dict[str, Any]] = []
    library_keys: set[str] = set()
    for index, raw in enumerate(library_rows):
        if not isinstance(raw, Mapping):
            raise MoviesSnapshotValidationError(f"library_entries[{index}] must be an object.")
        media_key = _bounded_text(
            raw.get("media_key"), f"library_entries[{index}].media_key", limit=96, required=True
        )
        lifecycle_status = _bounded_text(
            raw.get("lifecycle_status"),
            f"library_entries[{index}].lifecycle_status",
            limit=30,
            required=True,
        )
        if (
            media_key not in media_keys
            or media_key in library_keys
            or lifecycle_status not in _LIFECYCLE_STATUSES
        ):
            raise MoviesSnapshotValidationError(
                f"library_entries[{index}] is invalid or duplicated."
            )
        is_favorite = raw.get("is_favorite", False)
        if not isinstance(is_favorite, bool):
            raise MoviesSnapshotValidationError(
                f"library_entries[{index}].is_favorite must be boolean."
            )
        library_entries.append(
            {
                "media_key": media_key,
                "lifecycle_status": lifecycle_status,
                "is_favorite": is_favorite,
                "personal_rating": _optional_rating(raw.get("personal_rating")),
                "personal_label": _bounded_text(
                    raw.get("personal_label", ""),
                    f"library_entries[{index}].personal_label",
                    limit=160,
                ),
                "added_at": _timestamp(raw.get("added_at"), f"library_entries[{index}].added_at"),
                "first_watched_at": _timestamp(
                    raw.get("first_watched_at"), f"library_entries[{index}].first_watched_at"
                ),
                "last_watched_at": _timestamp(
                    raw.get("last_watched_at"), f"library_entries[{index}].last_watched_at"
                ),
                "completed_at": _timestamp(
                    raw.get("completed_at"), f"library_entries[{index}].completed_at"
                ),
                "manual_lifecycle_at": _timestamp(
                    raw.get("manual_lifecycle_at"), f"library_entries[{index}].manual_lifecycle_at"
                ),
            }
        )
        library_keys.add(media_key)

    progress: list[dict[str, Any]] = []
    progress_keys: set[tuple[str, str]] = set()
    for index, raw in enumerate(progress_rows):
        if not isinstance(raw, Mapping):
            raise MoviesSnapshotValidationError(f"progress[{index}] must be an object.")
        media_key = _bounded_text(
            raw.get("media_key"), f"progress[{index}].media_key", limit=96, required=True
        )
        season, episode = raw.get("season"), raw.get("episode")
        if (season is None) != (episode is None):
            raise MoviesSnapshotValidationError(f"progress[{index}] needs both season and episode.")
        if season is not None:
            season = _integer(season, f"progress[{index}].season", minimum=0, maximum=999)
            episode = _integer(episode, f"progress[{index}].episode", minimum=1, maximum=9999)
        scope_key = progress_scope_key(season=season, episode=episode)
        current_seconds = _integer(
            raw.get("current_seconds", 0), f"progress[{index}].current_seconds"
        )
        duration_seconds = _integer(
            raw.get("duration_seconds", 0), f"progress[{index}].duration_seconds"
        )
        if duration_seconds and current_seconds > duration_seconds:
            raise MoviesSnapshotValidationError(f"progress[{index}] cannot exceed its duration.")
        if media_key not in media_keys or (media_key, scope_key) in progress_keys:
            raise MoviesSnapshotValidationError(
                f"progress[{index}] has an unknown media key or duplicate scope."
            )
        if season is not None and _media_type_for_key(media_key) != "tv":
            raise MoviesSnapshotValidationError(
                f"progress[{index}] episode scope needs a TV media key."
            )
        completed = raw.get("completed", False)
        if not isinstance(completed, bool):
            raise MoviesSnapshotValidationError(f"progress[{index}].completed must be boolean.")
        progress.append(
            {
                "media_key": media_key,
                "season": season,
                "episode": episode,
                "current_seconds": current_seconds,
                "duration_seconds": duration_seconds,
                "completed": completed,
                "client_updated_at": _timestamp(
                    raw.get("client_updated_at"), f"progress[{index}].client_updated_at"
                ),
                "updated_at": _timestamp(raw.get("updated_at"), f"progress[{index}].updated_at"),
            }
        )
        progress_keys.add((media_key, scope_key))

    custom_lists: list[dict[str, Any]] = []
    list_keys: set[str] = set()
    for index, raw in enumerate(list_rows):
        if not isinstance(raw, Mapping):
            raise MoviesSnapshotValidationError(f"custom_lists[{index}] must be an object.")
        list_key = _bounded_text(
            raw.get("list_key"), f"custom_lists[{index}].list_key", limit=40, required=True
        )
        if not _LIST_KEY_PATTERN.fullmatch(list_key) or list_key in list_keys:
            raise MoviesSnapshotValidationError(
                f"custom_lists[{index}].list_key is invalid or duplicated."
            )
        raw_items = raw.get("items", [])
        if not isinstance(raw_items, list):
            raise MoviesSnapshotValidationError(f"custom_lists[{index}].items must be an array.")
        memberships: list[dict[str, Any]] = []
        membership_keys: set[str] = set()
        for item_index, item in enumerate(raw_items):
            if not isinstance(item, Mapping):
                raise MoviesSnapshotValidationError(
                    f"custom_lists[{index}].items[{item_index}] must be an object."
                )
            media_key = _bounded_text(
                item.get("media_key"),
                f"custom_lists[{index}].items[{item_index}].media_key",
                limit=96,
                required=True,
            )
            if media_key not in media_keys or media_key in membership_keys:
                raise MoviesSnapshotValidationError(
                    f"custom_lists[{index}].items[{item_index}] is invalid or duplicated."
                )
            memberships.append(
                {
                    "media_key": media_key,
                    "position": _integer(
                        item.get("position", item_index),
                        f"custom_lists[{index}].items[{item_index}].position",
                    ),
                    "added_at": _timestamp(
                        item.get("added_at"), f"custom_lists[{index}].items[{item_index}].added_at"
                    ),
                }
            )
            membership_keys.add(media_key)
        custom_lists.append(
            {
                "list_key": list_key,
                "title": _bounded_text(
                    raw.get("title"), f"custom_lists[{index}].title", limit=160, required=True
                ),
                "description": _bounded_text(
                    raw.get("description", ""), f"custom_lists[{index}].description", limit=2000
                ),
                "created_at": _timestamp(
                    raw.get("created_at"), f"custom_lists[{index}].created_at"
                ),
                "updated_at": _timestamp(
                    raw.get("updated_at"), f"custom_lists[{index}].updated_at"
                ),
                "items": memberships,
            }
        )
        list_keys.add(list_key)

    return {
        "schema_version": MOVIES_SNAPSHOT_SCHEMA_VERSION,
        "exported_at": _timestamp(payload.get("exported_at"), "exported_at"),
        "media": media,
        "library_entries": library_entries,
        "progress": progress,
        "custom_lists": custom_lists,
        "preferences": _normalize_preferences(payload.get("preferences")),
    }


def _snapshot_media(movie: Movie) -> dict[str, Any]:
    external_ids = dict(movie.external_ids or {})
    return {
        "media_key": movie.media_key,
        "media_type": movie.media_type,
        "title": movie.title,
        "original_title": movie.original_title or "",
        "year": movie.year,
        "external_ids": {
            key: external_ids[key]
            for key in ("tmdb_id", "tmdb_type", "imdb_id")
            if external_ids.get(key) not in {None, ""}
        },
    }


def export_movies_snapshot(*, owner_user_id: int) -> dict[str, Any]:
    """Export portable Movies state for the current local Dragon user."""

    entries = list(
        db.session.scalars(
            db.select(MovieLibraryEntry)
            .options(selectinload(MovieLibraryEntry.movie))
            .order_by(MovieLibraryEntry.media_key)
        )
    )
    progress_rows = list(
        db.session.scalars(
            db.select(MovieProgress)
            .options(selectinload(MovieProgress.movie))
            .order_by(MovieProgress.movie_id, MovieProgress.scope_key)
        )
    )
    lists = list(
        db.session.scalars(
            db.select(MovieCustomList)
            .where(MovieCustomList.owner_user_id == int(owner_user_id))
            .options(selectinload(MovieCustomList.items).selectinload(MovieCustomListItem.movie))
            .order_by(MovieCustomList.id)
        )
    )
    movies = {
        movie.media_key: movie
        for movie in [
            *(entry.movie for entry in entries),
            *(row.movie for row in progress_rows),
            *(item.movie for custom_list in lists for item in custom_list.items),
        ]
        if movie is not None
    }
    from app.admin.control_center import preference_store

    return {
        "schema_version": MOVIES_SNAPSHOT_SCHEMA_VERSION,
        "exported_at": _utc_iso(utc_now()),
        "media": [_snapshot_media(movies[key]) for key in sorted(movies)],
        "library_entries": [
            {
                "media_key": entry.media_key,
                "lifecycle_status": entry.lifecycle_status,
                "is_favorite": entry.is_favorite,
                "personal_rating": entry.personal_rating,
                "personal_label": entry.personal_label,
                "added_at": _utc_iso(entry.added_at),
                "first_watched_at": _utc_iso(entry.first_watched_at),
                "last_watched_at": _utc_iso(entry.last_watched_at),
                "completed_at": _utc_iso(entry.completed_at),
                "manual_lifecycle_at": _utc_iso(entry.manual_lifecycle_at),
            }
            for entry in entries
        ],
        "progress": [
            {
                "media_key": row.movie.media_key,
                "season": row.season,
                "episode": row.episode,
                "current_seconds": row.current_seconds,
                "duration_seconds": row.duration_seconds,
                "completed": row.completed,
                "client_updated_at": _utc_iso(row.client_updated_at),
                "updated_at": _utc_iso(row.updated_at),
            }
            for row in progress_rows
            if row.movie is not None
        ],
        "custom_lists": [
            {
                "list_key": custom_list.id,
                "title": custom_list.title,
                "description": custom_list.description,
                "created_at": _utc_iso(custom_list.created_at),
                "updated_at": _utc_iso(custom_list.updated_at),
                "items": [
                    {
                        "media_key": item.movie.media_key,
                        "position": item.position,
                        "added_at": _utc_iso(item.added_at),
                    }
                    for item in custom_list.items
                    if item.movie is not None
                ],
            }
            for custom_list in lists
        ],
        "preferences": preference_store().read()["sections"]["movies"]["movie_preferences"],
    }


def movies_snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    """Return a stable digest for a validated preview/apply confirmation."""

    normalized = validate_movies_snapshot(snapshot)
    serializable = _json_ready(normalized)
    encoded = json.dumps(serializable, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def preview_movies_snapshot(snapshot: Mapping[str, Any], *, owner_user_id: int) -> dict[str, Any]:
    """Return an explicit, read-only import plan for a valid snapshot."""

    normalized = validate_movies_snapshot(snapshot)
    media_keys = [item["media_key"] for item in normalized["media"]]
    entry_keys = [item["media_key"] for item in normalized["library_entries"]]
    existing_media = {
        row.media_key
        for row in db.session.scalars(db.select(Movie).where(Movie.media_key.in_(media_keys)))
    }
    existing_entries = {
        row.media_key
        for row in db.session.scalars(
            db.select(MovieLibraryEntry).where(MovieLibraryEntry.media_key.in_(entry_keys))
        )
    }
    media_by_key = {
        row.media_key: row.id
        for row in db.session.scalars(db.select(Movie).where(Movie.media_key.in_(media_keys)))
    }
    progress_scopes = {
        (item["media_key"], progress_scope_key(season=item["season"], episode=item["episode"]))
        for item in normalized["progress"]
        if item["media_key"] in media_by_key
    }
    existing_progress = {
        (movie.media_key, row.scope_key)
        for movie, row in db.session.execute(
            db.select(Movie, MovieProgress).join(MovieProgress, MovieProgress.movie_id == Movie.id)
        )
        if (movie.media_key, row.scope_key) in progress_scopes
    }
    current_lists = {
        row.id
        for row in db.session.scalars(
            db.select(MovieCustomList).where(MovieCustomList.owner_user_id == int(owner_user_id))
        )
    }
    return {
        "schema_version": normalized["schema_version"],
        "digest": movies_snapshot_digest(normalized),
        "media": {
            "create": len(set(media_keys) - existing_media),
            "keep": len(existing_media),
        },
        "library_entries": {
            "create": len(set(entry_keys) - existing_entries),
            "restore": len(existing_entries),
        },
        "progress": {
            "create": len(progress_scopes - existing_progress),
            "restore": len(existing_progress),
        },
        "custom_lists": {
            "create": len(
                {item["list_key"] for item in normalized["custom_lists"]} - current_lists
            ),
            "restore": len(
                current_lists & {item["list_key"] for item in normalized["custom_lists"]}
            ),
        },
        "membership_count": sum(len(item["items"]) for item in normalized["custom_lists"]),
        "merge_only": True,
    }


def apply_movies_snapshot(snapshot: Mapping[str, Any], *, owner_user_id: int) -> dict[str, Any]:
    """Apply one already-validated snapshot as an explicit, non-deleting restore."""

    normalized = validate_movies_snapshot(snapshot)
    list_keys = [item["list_key"] for item in normalized["custom_lists"]]
    foreign_list = db.session.scalar(
        db.select(MovieCustomList).where(
            MovieCustomList.id.in_(list_keys),
            MovieCustomList.owner_user_id != int(owner_user_id),
        )
    )
    if foreign_list is not None:
        raise MoviesSnapshotConflictError("A snapshot list key belongs to another local user.")

    media_by_key = {movie.media_key: movie for movie in db.session.scalars(db.select(Movie))}
    created_media = created_entries = restored_entries = created_progress = restored_progress = 0
    for item in normalized["media"]:
        movie = media_by_key.get(item["media_key"])
        if movie is None:
            movie = Movie(
                media_key=item["media_key"],
                title=item["title"],
                normalized_title=item["title"].casefold()[:300],
                original_title=item["original_title"] or None,
                media_type=item["media_type"],
                year=item["year"],
                external_ids=item["external_ids"],
                status="want_to_watch",
                source="snapshot",
            )
            db.session.add(movie)
            db.session.flush()
            media_by_key[movie.media_key] = movie
            created_media += 1

    for item in normalized["library_entries"]:
        movie = media_by_key[item["media_key"]]
        entry = db.session.get(MovieLibraryEntry, item["media_key"])
        if entry is None:
            entry = MovieLibraryEntry(
                media_key=movie.media_key,
                movie_id=movie.id,
                lifecycle_status=item["lifecycle_status"],
                is_favorite=item["is_favorite"],
                personal_rating=item["personal_rating"],
                personal_label=item["personal_label"],
                added_at=item["added_at"] or utc_now(),
                first_watched_at=item["first_watched_at"],
                last_watched_at=item["last_watched_at"],
                completed_at=item["completed_at"],
                manual_lifecycle_at=item["manual_lifecycle_at"],
            )
            db.session.add(entry)
            created_entries += 1
        else:
            for key, value in item.items():
                if key != "media_key":
                    setattr(entry, key, value)
            restored_entries += 1
        movie.status = (
            "watched" if item["lifecycle_status"] == "watched" else item["lifecycle_status"]
        )
        movie.personal_score = item["personal_rating"]

    for item in normalized["progress"]:
        movie = media_by_key[item["media_key"]]
        scope = progress_scope_key(season=item["season"], episode=item["episode"])
        row = db.session.scalar(
            db.select(MovieProgress).where(
                MovieProgress.movie_id == movie.id,
                MovieProgress.scope_key == scope,
            )
        )
        if row is None:
            row = MovieProgress(
                movie_id=movie.id,
                season=item["season"],
                episode=item["episode"],
                current_seconds=item["current_seconds"],
                duration_seconds=item["duration_seconds"],
                completed=item["completed"],
                client_updated_at=item["client_updated_at"],
                updated_at=item["updated_at"] or utc_now(),
            )
            db.session.add(row)
            created_progress += 1
        else:
            for key, value in item.items():
                if key != "media_key":
                    setattr(row, key, value)
            restored_progress += 1

    created_lists = restored_lists = created_memberships = 0
    for item in normalized["custom_lists"]:
        custom_list = db.session.get(MovieCustomList, item["list_key"])
        if custom_list is None:
            custom_list = MovieCustomList(
                id=item["list_key"],
                owner_user_id=int(owner_user_id),
                title=item["title"],
                description=item["description"],
                created_at=item["created_at"] or utc_now(),
                updated_at=item["updated_at"] or utc_now(),
            )
            db.session.add(custom_list)
            created_lists += 1
        else:
            custom_list.title = item["title"]
            custom_list.description = item["description"]
            custom_list.updated_at = item["updated_at"] or utc_now()
            restored_lists += 1
        for membership in item["items"]:
            movie = media_by_key[membership["media_key"]]
            existing = db.session.get(MovieCustomListItem, (custom_list.id, movie.id))
            if existing is None:
                db.session.add(
                    MovieCustomListItem(
                        custom_list_id=custom_list.id,
                        movie_id=movie.id,
                        position=membership["position"],
                        added_at=membership["added_at"] or utc_now(),
                    )
                )
                created_memberships += 1
            else:
                existing.position = membership["position"]

    db.session.commit()
    from app.admin.control_center import preference_store

    preference_store().set_movie_preferences(normalized["preferences"])
    return {
        "media": {"created": created_media},
        "library_entries": {"created": created_entries, "restored": restored_entries},
        "progress": {"created": created_progress, "restored": restored_progress},
        "custom_lists": {
            "created": created_lists,
            "restored": restored_lists,
            "memberships_created": created_memberships,
        },
        "merge_only": True,
    }


def _json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return _utc_iso(value)
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value
