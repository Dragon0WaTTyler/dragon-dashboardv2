"""Shared, cache-first Movies and Series browse engine."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from flask import current_app

from app.movies.external_library import tmdb_catalog_provider
from app.movies.integrations import MediaIntegrationError

BROWSE_CACHE_TTL_SECONDS = 5 * 60
GENRE_CACHE_TTL_SECONDS = 24 * 60 * 60
PROVIDER_CACHE_TTL_SECONDS = 24 * 60 * 60
BROWSE_SORTS = {"popular", "rating", "newest", "title"}


@dataclass(frozen=True, slots=True)
class BrowseQuery:
    media_type: str
    genre_id: int | None
    year: int | None
    provider_id: int | None
    region: str
    sort: str
    page: int


def parse_browse_query(media_type: str, values: Any) -> tuple[BrowseQuery, dict[str, str]]:
    normalized_type = media_type.strip().lower()
    if normalized_type not in {"movie", "tv"}:
        raise ValueError("Browse media type must be movie or series.")
    errors: dict[str, str] = {}
    genre_id = _bounded_int(
        values.get("genre"), minimum=1, maximum=99999, errors=errors, name="genre"
    )
    year = _bounded_int(
        values.get("year"), minimum=1800, maximum=2200, errors=errors, name="year"
    )
    provider_id = _bounded_int(
        values.get("provider"), minimum=1, maximum=99999, errors=errors, name="provider"
    )
    region = str(values.get("region") or "US").strip().upper()
    if len(region) != 2 or not region.isalpha():
        errors["region"] = "Use a two-letter region code."
        region = "US"
    page = (
        _bounded_int(
            values.get("page"), minimum=1, maximum=500, errors=errors, name="page"
        )
        or 1
    )
    sort = str(values.get("sort") or "popular").strip().lower()
    if sort not in BROWSE_SORTS:
        errors["sort"] = "Choose a supported sort order."
        sort = "popular"
    return BrowseQuery(normalized_type, genre_id, year, provider_id, region, sort, page), errors


def browse_catalog(query: BrowseQuery) -> dict[str, Any]:
    """Return cache-first remote cards and genre options for either media type."""

    provider = tmdb_catalog_provider()
    if not getattr(provider, "configured", True):
        return {
            "items": [],
            "genres": [],
            "page": query.page,
            "total_pages": query.page,
            "error": "TMDB is not configured.",
        }
    cache = current_app.extensions.setdefault("dragon_movies_browse_cache", {})
    now = time.monotonic()
    genre_key = f"genres:{query.media_type}"
    genres = _cached_genres(cache, genre_key, provider, query.media_type, now)
    providers = _cached_providers(cache, provider, query.media_type, query.region, now)
    query_key = (
        f"browse:{query.media_type}:{query.genre_id or ''}:{query.year or ''}:{query.provider_id or ''}:{query.region}:"
        f"{query.sort}:{query.page}"
    )
    cached = cache.get(query_key)
    if isinstance(cached, dict) and float(cached.get("expires_at") or 0) > now:
        return {**cached["value"], "genres": genres, "providers": providers, "error": ""}
    try:
        discover_kwargs: dict[str, Any] = {
            "genre_id": query.genre_id,
            "year": query.year,
            "sort": query.sort,
            "page": query.page,
        }
        if query.provider_id:
            discover_kwargs["provider_id"] = query.provider_id
            discover_kwargs["region"] = query.region
        payload = provider.discover(query.media_type, **discover_kwargs)
    except MediaIntegrationError as exc:
        return {
            "items": [],
            "genres": genres, "providers": providers,
            "page": query.page,
            "total_pages": query.page,
            "error": str(exc),
        }
    value = {
        "items": [
            {**item, "detail_url": f"/movies/discover/{query.media_type}/{item['tmdb_id']}"}
            for item in payload["items"]
        ],
        "page": int(payload["page"]),
        "total_pages": int(payload["total_pages"]),
    }
    cache[query_key] = {"expires_at": now + BROWSE_CACHE_TTL_SECONDS, "value": value}
    return {**value, "genres": genres, "providers": providers, "error": ""}


def _cached_providers(
    cache: dict[str, Any], provider: Any, media_type: str, region: str, now: float
) -> list[dict[str, Any]]:
    key = f"providers:{media_type}:{region}"
    cached = cache.get(key)
    if isinstance(cached, dict) and float(cached.get("expires_at") or 0) > now:
        return list(cached.get("value") or [])
    if not hasattr(provider, "provider_catalog"):
        return []
    try:
        value = provider.provider_catalog(media_type, region=region)
    except MediaIntegrationError:
        return list(cached.get("value") or []) if isinstance(cached, dict) else []
    providers = sorted(value, key=lambda item: item["name"].casefold())
    cache[key] = {"expires_at": now + PROVIDER_CACHE_TTL_SECONDS, "value": providers}
    return providers


def _cached_genres(
    cache: dict[str, Any], genre_key: str, provider: Any, media_type: str, now: float
) -> list[dict[str, Any]]:
    cached = cache.get(genre_key)
    if isinstance(cached, dict) and float(cached.get("expires_at") or 0) > now:
        return list(cached.get("value") or [])
    if not hasattr(provider, "genres"):
        return []
    try:
        value = provider.genres(media_type)
    except MediaIntegrationError:
        return list(cached.get("value") or []) if isinstance(cached, dict) else []
    genres = sorted(
        ({"id": int(item["id"]), "name": str(item["name"])} for item in value),
        key=lambda item: item["name"].casefold(),
    )
    cache[genre_key] = {"expires_at": now + GENRE_CACHE_TTL_SECONDS, "value": genres}
    return genres


def _bounded_int(
    value: Any, *, minimum: int, maximum: int, errors: dict[str, str], name: str
) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        errors[name] = "Enter a valid number."
        return None
    if not minimum <= number <= maximum:
        errors[name] = f"Choose a value between {minimum} and {maximum}."
        return None
    return number
