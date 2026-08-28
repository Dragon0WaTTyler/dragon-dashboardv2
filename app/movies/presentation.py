"""Canonical catalog-facing view contract for Movies and TV detail pages.

Catalog data can come from a persisted ``Movie`` record or directly from TMDB.
This module deliberately normalizes only presentation data.  Personal state,
progress, and Dragon playback capabilities remain separate overlays so a
discovery preview cannot accidentally become library state.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value or [] if isinstance(item, Mapping)]


def _thumbnail(trailer: dict[str, Any]) -> dict[str, Any]:
    item = dict(trailer)
    if item.get("thumbnail_url"):
        return item
    url = str(item.get("url") or "")
    key = url.split("v=", 1)[1].split("&", 1)[0] if "v=" in url else ""
    if key:
        item["thumbnail_url"] = f"https://img.youtube.com/vi/{key}/hqdefault.jpg"
    return item


def _related(items: list[dict[str, Any]], *, media_type: str, tmdb_id: int | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        item_type = str(item.get("media_type") or media_type).lower()
        try:
            item_id = int(item.get("tmdb_id"))
        except (TypeError, ValueError):
            continue
        if item_type not in {"movie", "tv"} or (item_type == media_type and item_id == tmdb_id):
            continue
        key = f"{item_type}:{item_id}"
        if key in seen:
            continue
        seen.add(key)
        result.append({**item, "media_type": item_type, "tmdb_id": item_id})
        if len(result) == 12:
            break
    return result


def canonical_detail_presentation(
    record: Mapping[str, Any],
    *,
    is_saved: bool,
    personal: Mapping[str, Any] | None = None,
    playback: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one catalog/personal/playback contract for local and TMDB detail.

    ``record`` may be the persisted ``movie_detail`` dictionary or a TMDB
    ``discover_item`` dictionary.  The output intentionally keeps the three
    ownership domains isolated under ``catalog``, ``personal``, and
    ``playback``.
    """

    raw = dict(record)
    tmdb = _mapping(raw.get("tmdb_detail"))
    media_type = str(raw.get("media_type") or "movie").lower()
    try:
        tmdb_id = int(raw.get("tmdb_id") or _mapping(raw.get("external_ids")).get("tmdb_id"))
    except (TypeError, ValueError):
        tmdb_id = None

    trailers = [_thumbnail(item) for item in _list(raw.get("trailers") or tmdb.get("trailers"))]
    related_inputs = _list(raw.get("related")) or (
        _list(tmdb.get("similar")) + _list(tmdb.get("recommendations"))
    )
    genres = _list(raw.get("genres"))
    genre_names = [str(item.get("name") or "").strip() for item in genres]
    genre_names = [name for name in genre_names if name]

    catalog = {
        "tmdb_id": tmdb_id,
        "media_type": media_type,
        "title": str(raw.get("title") or "Untitled"),
        "original_title": str(raw.get("original_title") or ""),
        "year": raw.get("year"),
        "tagline": str(raw.get("tagline") or tmdb.get("tagline") or ""),
        "overview": str(raw.get("overview") or ""),
        "poster_url": str(raw.get("poster_url") or ""),
        "backdrop_url": str(raw.get("backdrop_url") or tmdb.get("backdrop_url") or ""),
        "rating": raw.get("tmdb_rating", raw.get("rating", tmdb.get("tmdb_rating"))),
        "certification": str(raw.get("certification") or tmdb.get("certification") or ""),
        "genres": genres,
        "genre_names": genre_names,
        "original_language": str(raw.get("original_language") or tmdb.get("original_language") or ""),
        "countries": list(raw.get("countries") or tmdb.get("countries") or []),
        "runtime_minutes": raw.get("runtime_minutes"),
        "cast": _list(raw.get("cast")),
        "trailers": trailers,
        "reviews": _list(raw.get("reviews") or tmdb.get("reviews")),
        "related": _related(related_inputs, media_type=media_type, tmdb_id=tmdb_id),
        "release_date": str(raw.get("release_date") or ""),
        "production_companies": _list(raw.get("production_companies")),
        "budget": raw.get("budget"),
        "revenue": raw.get("revenue"),
        "provider_availability": _list(raw.get("provider_availability")),
        "seasons": _list(raw.get("seasons")),
    }
    return {
        "identity": {"id": raw.get("id") or raw.get("local_id"), "tmdb_id": tmdb_id, "media_type": media_type},
        "catalog": catalog,
        "personal": {
            "is_saved": is_saved,
            "status": raw.get("status") if is_saved else None,
            "favorite": bool(raw.get("is_favorite")) if is_saved else False,
            "personal_rating": raw.get("personal_score") if is_saved else None,
            "lists": list((personal or {}).get("lists") or []),
            "progress": raw.get("progress") if is_saved else None,
        },
        "playback": {
            "can_play": bool((playback or {}).get("can_play")),
            "can_preview": bool((playback or {}).get("can_preview")),
            "configured_sources_present": bool((playback or {}).get("configured_sources_present")),
        },
    }
