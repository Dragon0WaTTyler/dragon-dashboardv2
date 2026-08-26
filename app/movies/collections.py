"""Declarative, cache-first editorial collections for Movies V2.

Collection definitions describe discovery only.  They are deliberately separate
from a person's library, playback sources, and provider availability.  A
definition may use a broad TMDB discover filter, but it never asserts an
unverified factual claim such as an award or festival selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.movies.browse import BrowseQuery, browse_catalog

COLLECTION_TYPES = frozenset(
    {
        "curated_editorial",
        "award",
        "festival",
        "seasonal",
        "provider",
        "dynamic_query",
    }
)


@dataclass(frozen=True, slots=True)
class MovieCollectionDefinition:
    """A stable display/query contract for one Dragon discovery collection."""

    id: str
    title: str
    description: str
    media_type: str
    collection_type: str
    genre_id: int | None = None
    sort: str = "popular"
    enabled: bool = True
    requires_verified_source: bool = False


# These are editorial discovery prompts, not claims about a title's awards,
# festival history, true-story provenance, or playback availability.  Award and
# festival collection types are intentionally supported by the contract but are
# not exposed until Dragon has a reliable, reviewable source of that metadata.
MOVIE_COLLECTIONS: tuple[MovieCollectionDefinition, ...] = (
    MovieCollectionDefinition(
        id="psychological-thrillers",
        title="Psychological thrillers",
        description="An editorial route into tense, character-led thrillers.",
        media_type="movie",
        collection_type="curated_editorial",
        genre_id=53,
    ),
    MovieCollectionDefinition(
        id="mind-bending-movies",
        title="Mind-bending movies",
        description="A Dragon-curated starting point for imaginative science fiction.",
        media_type="movie",
        collection_type="curated_editorial",
        genre_id=878,
    ),
    MovieCollectionDefinition(
        id="action-and-adrenaline",
        title="Action & adrenaline",
        description="A fast-moving editorial route through TMDB action discovery.",
        media_type="movie",
        collection_type="curated_editorial",
        genre_id=28,
    ),
    MovieCollectionDefinition(
        id="halloween-watchlist",
        title="Halloween watchlist",
        description="A seasonal Dragon collection built from horror discovery.",
        media_type="movie",
        collection_type="seasonal",
        genre_id=27,
    ),
    MovieCollectionDefinition(
        id="highly-rated-series",
        title="Highly rated series",
        description="A dynamic TMDB audience-rating view for series exploration.",
        media_type="tv",
        collection_type="dynamic_query",
        sort="rating",
    ),
)


def active_movie_collections() -> tuple[MovieCollectionDefinition, ...]:
    """Return only collections that have a safe, supported public definition."""

    return tuple(
        definition
        for definition in MOVIE_COLLECTIONS
        if definition.enabled
        and not definition.requires_verified_source
        and definition.collection_type in COLLECTION_TYPES
    )


def movie_collection(collection_id: str) -> MovieCollectionDefinition | None:
    """Resolve an active collection from its stable URL identifier."""

    normalized_id = str(collection_id or "").strip().lower()
    return next(
        (
            definition
            for definition in active_movie_collections()
            if definition.id == normalized_id
        ),
        None,
    )


def collection_query(
    definition: MovieCollectionDefinition, values: Any
) -> BrowseQuery:
    """Build a bounded catalog query while keeping collection filters canonical."""

    try:
        page = int(str(values.get("page") or "1"))
    except (TypeError, ValueError):
        page = 1
    return BrowseQuery(
        media_type=definition.media_type,
        genre_id=definition.genre_id,
        year=None,
        provider_id=None,
        region="US",
        sort=definition.sort,
        page=max(1, min(page, 500)),
    )


def collection_catalog(
    definition: MovieCollectionDefinition, values: Any
) -> tuple[BrowseQuery, dict[str, Any]]:
    """Fetch a collection through the shared browse cache; no personal writes."""

    query = collection_query(definition, values)
    return query, browse_catalog(query)
