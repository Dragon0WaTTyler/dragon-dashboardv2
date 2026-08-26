"""Movies-owned discovery rail contracts and cache-first projections."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from flask import current_app

from app.movies.external_library import tmdb_catalog_provider
from app.movies.integrations import MediaIntegrationError

DISCOVERY_RAIL_CACHE_TTL_SECONDS = 5 * 60


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
