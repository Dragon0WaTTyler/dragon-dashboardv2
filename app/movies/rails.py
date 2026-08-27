"""Movies-owned discovery rail contracts and cache-first projections."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from flask import current_app

from app.movies.external_library import tmdb_catalog_provider
from app.movies.integrations import MediaIntegrationError

DISCOVERY_RAIL_CACHE_TTL_SECONDS = 5 * 60
PROVIDER_CONTEXT_CACHE_TTL_SECONDS = 5 * 60
PROVIDER_CONTEXT_LIMIT = 14
PROVIDER_RAIL_LIMIT = 12


@dataclass(frozen=True, slots=True)
class DiscoveryRailDefinition:
    """A display contract; remote catalog data never becomes personal state here."""

    id: str
    title: str
    subtitle: str
    content_type: str
    rail_type: str
    source: str
    query: str
    limit: int = 12
    view_all_target: str = ""
    enabled: bool = True


DISCOVERY_RAILS: tuple[DiscoveryRailDefinition, ...] = (
    DiscoveryRailDefinition(
        id="trending_movies",
        title="Trending Movies",
        subtitle="What people are watching now",
        content_type="movie",
        rail_type="poster",
        source="tmdb_trending",
        query="week",
    ),
    DiscoveryRailDefinition(
        id="trending_series",
        title="Trending Series",
        subtitle="Series with momentum right now",
        content_type="tv",
        rail_type="poster",
        source="tmdb_trending",
        query="week",
    ),
    DiscoveryRailDefinition(
        id="popular_movies",
        title="Popular Movies",
        subtitle="Popular on TMDB",
        content_type="movie",
        rail_type="poster",
        source="tmdb_catalog",
        query="popular",
    ),
    DiscoveryRailDefinition(
        id="popular_series",
        title="Popular Series",
        subtitle="Popular on TMDB",
        content_type="tv",
        rail_type="poster",
        source="tmdb_catalog",
        query="popular",
    ),
    DiscoveryRailDefinition(
        id="top_rated_movies",
        title="Top Rated Movies",
        subtitle="Highly rated by TMDB audiences",
        content_type="movie",
        rail_type="poster",
        source="tmdb_catalog",
        query="top_rated",
    ),
    DiscoveryRailDefinition(
        id="top_rated_series",
        title="Top Rated Series",
        subtitle="Highly rated by TMDB audiences",
        content_type="tv",
        rail_type="poster",
        source="tmdb_catalog",
        query="top_rated",
    ),
    DiscoveryRailDefinition(
        id="upcoming_movies",
        title="Upcoming Movies",
        subtitle="On the TMDB release calendar",
        content_type="movie",
        rail_type="poster",
        source="tmdb_catalog",
        query="upcoming",
    ),
    DiscoveryRailDefinition(
        id="now_playing_movies",
        title="Now in Theaters",
        subtitle="Current theatrical releases on TMDB",
        content_type="movie",
        rail_type="poster",
        source="tmdb_catalog",
        query="now_playing",
    ),
    DiscoveryRailDefinition(
        id="top_10_movies",
        title="Top 10 Movies",
        subtitle="Ranked from this week's TMDB movie trend",
        content_type="movie",
        rail_type="ranked",
        source="tmdb_trending",
        query="week",
        limit=10,
    ),
)


def discovery_rails() -> list[dict[str, Any]]:
    """Return Discovery rails from a single app-scoped TTL cache.

    A catalog card remains a remote discovery result. It points at Dragon's
    existing discover route and is never inserted into the personal library by
    rendering a rail.
    """

    provider = tmdb_catalog_provider()
    cache = current_app.extensions.setdefault("dragon_movies_discovery_rails", {})
    now = time.monotonic()
    rails: list[dict[str, Any]] = []
    for definition in DISCOVERY_RAILS:
        if not definition.enabled:
            continue
        items = _cached_or_fetch(
            cache, provider, definition, _source_limit(definition), now
        )
        if not items:
            continue
        rails.append(
            {
                "id": definition.id,
                "title": definition.title,
                "subtitle": definition.subtitle,
                "content_type": definition.content_type,
                "rail_type": definition.rail_type,
                "source": definition.source,
                "view_all_target": definition.view_all_target,
                "items": items,
            }
        )
    return rails


def provider_context(
    *, region: str = "US", selected_provider_id: int | None = None
) -> dict[str, Any]:
    """Return one shared availability-provider selection and its two rails.

    Provider data here is TMDB availability metadata.  It is deliberately kept
    separate from Dragon playback/source acquisition, and all remote results
    remain cache-backed discovery cards until a user imports a title.
    """

    normalized_region = str(region or "US").strip().upper()
    if len(normalized_region) != 2 or not normalized_region.isalpha():
        normalized_region = "US"
    provider = tmdb_catalog_provider()
    cache = current_app.extensions.setdefault("dragon_movies_provider_context", {})
    catalog_cache = current_app.extensions.setdefault("dragon_movies_provider_catalog", {})
    now = time.monotonic()
    catalog = _provider_catalog_union(
        catalog_cache, provider, normalized_region, now
    )
    if not catalog or not getattr(provider, "configured", True):
        return {
            "region": normalized_region,
            "providers": catalog,
            "selected_provider": None,
            "rails": [],
            "error": "TMDB availability providers are not configured.",
        }
    selected = next(
        (item for item in catalog if item["id"] == selected_provider_id), None
    )
    selected = selected or catalog[0]
    cache_key = f"{normalized_region}:{selected['id']}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and float(cached.get("expires_at") or 0) > now:
        return {
            "region": normalized_region,
            "providers": catalog,
            "selected_provider": selected,
            "rails": list(cached.get("rails") or []),
            "error": "",
        }
    rails: list[dict[str, Any]] = []
    errors: list[str] = []
    for media_type, title in (
        ("movie", f"Movies on {selected['name']}"),
        ("tv", f"TV Series on {selected['name']}"),
    ):
        try:
            payload = provider.discover(
                media_type,
                provider_id=int(selected["id"]),
                region=normalized_region,
                sort="popular",
                page=1,
            )
            items = _normalize_items(
                payload.get("items") if isinstance(payload, dict) else [],
                media_type,
                PROVIDER_RAIL_LIMIT,
            )
        except MediaIntegrationError as exc:
            errors.append(str(exc))
            items = []
        if items:
            rails.append(
                {
                    "id": f"provider_{media_type}",
                    "title": title,
                    "subtitle": f"Available in {normalized_region}",
                    "content_type": media_type,
                    "rail_type": "poster",
                    "source": "tmdb_availability",
                    "provider_id": int(selected["id"]),
                    "provider_name": selected["name"],
                    "items": items,
                }
            )
    if rails:
        cache[cache_key] = {
            "expires_at": now + PROVIDER_CONTEXT_CACHE_TTL_SECONDS,
            "rails": rails,
        }
    elif isinstance(cached, dict):
        rails = list(cached.get("rails") or [])
    return {
        "region": normalized_region,
        "providers": catalog,
        "selected_provider": selected,
        "rails": rails,
        "error": "; ".join(errors),
    }


def _provider_catalog_union(
    cache: dict[str, Any], provider: Any, region: str, now: float
) -> list[dict[str, Any]]:
    key = f"{region}"
    cached = cache.get(key)
    if isinstance(cached, dict) and float(cached.get("expires_at") or 0) > now:
        return list(cached.get("value") or [])
    if not getattr(provider, "configured", True) or not hasattr(provider, "provider_catalog"):
        return list(cached.get("value") or []) if isinstance(cached, dict) else []
    merged: dict[int, dict[str, Any]] = {}
    for media_type in ("movie", "tv"):
        try:
            values = provider.provider_catalog(media_type, region=region)
        except MediaIntegrationError:
            continue
        for item in values or []:
            try:
                provider_id = int(item["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if not item.get("name"):
                continue
            merged.setdefault(
                provider_id,
                {
                    "id": provider_id,
                    "name": str(item["name"]),
                    "logo_url": str(item.get("logo_url") or ""),
                },
            )
    priority = {
        "netflix": 0,
        "prime video": 1,
        "disney plus": 2,
        "disney+": 2,
        "apple tv+": 3,
        "hulu": 4,
        "max": 5,
    }
    value = sorted(
        merged.values(),
        key=lambda item: (priority.get(item["name"].casefold(), 99), item["name"].casefold()),
    )[:PROVIDER_CONTEXT_LIMIT]
    if value:
        cache[key] = {
            "expires_at": now + 24 * 60 * 60,
            "value": value,
        }
        return value
    return list(cached.get("value") or []) if isinstance(cached, dict) else []


def _source_limit(definition: DiscoveryRailDefinition) -> int:
    return max(
        item.limit
        for item in DISCOVERY_RAILS
        if item.source == definition.source
        and item.content_type == definition.content_type
        and item.query == definition.query
    )


def _cached_or_fetch(
    cache: dict[str, Any],
    provider: Any,
    definition: DiscoveryRailDefinition,
    source_limit: int,
    now: float,
) -> list[dict[str, Any]]:
    cache_key = f"{definition.source}:{definition.content_type}:{definition.query}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and float(cached.get("expires_at") or 0) > now:
        return list(cached.get("items") or [])[: definition.limit]
    if not getattr(provider, "configured", True):
        return []
    try:
        source_items = _fetch_source(provider, definition, source_limit)
    except MediaIntegrationError:
        if isinstance(cached, dict):
            return list(cached.get("items") or [])[: definition.limit]
        return []
    items = _normalize_items(source_items, definition.content_type, source_limit)
    cache[cache_key] = {
        "expires_at": now + DISCOVERY_RAIL_CACHE_TTL_SECONDS,
        "items": items,
    }
    return items[: definition.limit]


def _fetch_source(
    provider: Any, definition: DiscoveryRailDefinition, limit: int
) -> list[dict[str, Any]]:
    if definition.source == "tmdb_trending" and hasattr(provider, "trending"):
        return provider.trending(definition.content_type, limit=limit)
    if definition.source == "tmdb_catalog" and hasattr(provider, "catalog"):
        return provider.catalog(definition.content_type, definition.query, limit=limit)
    return []


def _normalize_items(
    source_items: Any, media_type: str, limit: int
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for source_item in source_items or []:
        try:
            tmdb_id = int(source_item["tmdb_id"])
        except (KeyError, TypeError, ValueError):
            continue
        item_type = str(source_item.get("media_type") or media_type)
        identity = (item_type, tmdb_id)
        if item_type != media_type or identity in seen:
            continue
        seen.add(identity)
        items.append(
            {
                **source_item,
                "tmdb_id": tmdb_id,
                "media_type": item_type,
                "rank": len(items) + 1,
                "detail_url": f"/movies/discover/{item_type}/{tmdb_id}",
            }
        )
        if len(items) >= limit:
            break
    return items
