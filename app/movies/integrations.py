from __future__ import annotations

import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests
from defusedxml import ElementTree as ET

from app.movies.scoring import notion_score_options, score_option_for_input


class MediaIntegrationError(RuntimeError):
    """A credential-safe failure from an external movie integration."""


class TmdbCatalogProvider:
    RELEASE_ALIAS_CACHE_TTL_SECONDS = 24 * 60 * 60

    def __init__(
        self,
        *,
        api_key: str = "",
        read_access_token: str = "",
        session: requests.Session | None = None,
        timeout_seconds: float = 15,
    ) -> None:
        self.api_key = api_key.strip()
        self.read_access_token = read_access_token.strip()
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self._release_alias_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
        self._alternate_title_cache: dict[tuple[str, int], tuple[float, list[str]]] = {}

    @property
    def configured(self) -> bool:
        return bool(self.api_key or self.read_access_token)

    def search(self, query: str, media_type: str = "all", *, limit: int = 20) -> list[dict]:
        payload = self._request(
            "/search/multi",
            {"query": query, "include_adult": "false", "language": "en-US", "page": 1},
        )
        ranked: list[tuple[float, dict, dict]] = []
        normalized_query = _normalize_title(query)
        for item in payload.get("results") or []:
            item_type = str(item.get("media_type") or "")
            if item_type not in {"movie", "tv"}:
                continue
            if media_type in {"movie", "tv"} and item_type != media_type:
                continue
            summary = self._summary(item, item_type)
            ranked.append((self._search_score(summary, normalized_query, item), summary, item))
        ranked.sort(
            key=lambda pair: (
                -pair[0],
                pair[1]["title"].casefold(),
                -(pair[1].get("year") or 0),
            )
        )
        enriched: list[tuple[float, dict, dict]] = []
        for _score, summary, source in ranked[: max(1, min(limit, 12))]:
            aliases = self.alternative_titles(summary["media_type"], summary["tmdb_id"])
            if aliases:
                summary = {**summary, "alternate_titles": aliases}
            enriched.append(
                (self._search_score(summary, normalized_query, source), summary, source)
            )
        enriched.sort(
            key=lambda pair: (
                -pair[0],
                pair[1]["title"].casefold(),
                -(pair[1].get("year") or 0),
            )
        )
        return [summary for _, summary, _ in enriched[: max(1, min(limit, 40))]]

    def alternative_titles(self, media_type: str, tmdb_id: int) -> list[str]:
        """Return cached alternate titles; failure never makes a search fail."""

        key = (media_type, int(tmdb_id))
        cached = self._alternate_title_cache.get(key)
        if cached and cached[0] > time.monotonic():
            return list(cached[1])
        try:
            payload = self._request(f"/{media_type}/{int(tmdb_id)}/alternative_titles")
            aliases = [
                str(item.get("title") or "").strip()
                for item in payload.get("titles") or []
                if isinstance(item, dict) and str(item.get("title") or "").strip()
            ]
        except MediaIntegrationError:
            aliases = []
        deduplicated = list(dict.fromkeys(aliases))
        self._alternate_title_cache[key] = (
            time.monotonic() + self.RELEASE_ALIAS_CACHE_TTL_SECONDS,
            deduplicated,
        )
        return deduplicated

    def clear_alternate_title_cache(self) -> int:
        """Clear only disposable search aliases and return the removed count."""

        removed = len(self._alternate_title_cache)
        self._alternate_title_cache.clear()
        return removed

    def lookup_tmdb_id(self, tmdb_id: int, media_type: str = "all") -> list[dict]:
        """Resolve an explicitly requested TMDB ID without pretending it is text search."""

        types = (media_type,) if media_type in {"movie", "tv"} else ("movie", "tv")
        matches = []
        for item_type in types:
            try:
                matches.append(self.details(item_type, int(tmdb_id)))
            except MediaIntegrationError:
                continue
        return matches

    def trending(self, media_type: str, *, limit: int = 20) -> list[dict]:
        """Return a ranked TMDB trend snapshot without mutating Dragon state."""

        if media_type not in {"movie", "tv"}:
            raise MediaIntegrationError("Trending media type must be movie or series.")
        payload = self._request(f"/trending/{media_type}/week", {"language": "en-US"})
        return [
            self._summary(item, media_type)
            for item in (payload.get("results") or [])[: max(1, min(limit, 40))]
            if item.get("id")
        ]

    def catalog(self, media_type: str, kind: str, *, limit: int = 20) -> list[dict]:
        """Return one normalized TMDB browse slice without personal-state writes."""

        paths = {
            ("movie", "popular"): "/movie/popular",
            ("tv", "popular"): "/tv/popular",
            ("movie", "top_rated"): "/movie/top_rated",
            ("tv", "top_rated"): "/tv/top_rated",
            ("movie", "upcoming"): "/movie/upcoming",
            ("movie", "now_playing"): "/movie/now_playing",
        }
        path = paths.get((media_type, kind))
        if path is None:
            raise MediaIntegrationError("Unsupported TMDB catalog rail.")
        payload = self._request(path, {"language": "en-US", "page": 1})
        return [
            self._summary(item, media_type)
            for item in (payload.get("results") or [])[: max(1, min(limit, 40))]
            if item.get("id")
        ]

    def discover(
        self,
        media_type: str,
        *,
        genre_id: int | None = None,
        year: int | None = None,
        provider_id: int | None = None,
        region: str = "US",
        sort: str = "popular",
        page: int = 1,
    ) -> dict[str, Any]:
        """Fetch one shareable TMDB browse page, without creating Dragon data."""

        if media_type not in {"movie", "tv"}:
            raise MediaIntegrationError("Browse media type must be movie or series.")
        sort_by = {
            "popular": "popularity.desc",
            "rating": "vote_average.desc",
            "newest": "primary_release_date.desc"
            if media_type == "movie"
            else "first_air_date.desc",
            "title": "original_title.asc" if media_type == "movie" else "original_name.asc",
        }.get(sort)
        if sort_by is None:
            raise MediaIntegrationError("Unsupported TMDB browse sort.")
        params: dict[str, Any] = {
            "language": "en-US",
            "include_adult": "false",
            "sort_by": sort_by,
            "page": max(1, min(int(page), 500)),
        }
        if genre_id:
            params["with_genres"] = int(genre_id)
        if year:
            year_key = (
                "primary_release_year" if media_type == "movie" else "first_air_date_year"
            )
            params[year_key] = int(year)
        if provider_id:
            params["with_watch_providers"] = int(provider_id)
            params["watch_region"] = str(region or "US").upper()[:2]
        payload = self._request(f"/discover/{media_type}", params)
        return {
            "items": [
                self._summary(item, media_type)
                for item in payload.get("results") or []
                if item.get("id")
            ],
            "page": int(payload.get("page") or params["page"]),
            "total_pages": min(500, int(payload.get("total_pages") or 1)),
        }

    def watch_providers(self, media_type: str, tmdb_id: int, *, region: str = "US") -> list[dict]:
        if media_type not in {"movie", "tv"}:
            raise MediaIntegrationError("Provider availability needs a movie or series.")
        payload = self._request(f"/{media_type}/{int(tmdb_id)}/watch/providers", {})
        region_data = (payload.get("results") or {}).get(str(region or "US").upper()) or {}
        providers: dict[int, dict] = {}
        for availability_type in ("flatrate", "free", "ads", "rent", "buy"):
            for item in region_data.get(availability_type) or []:
                provider_id = _optional_int(item.get("provider_id"))
                if not provider_id or not item.get("provider_name"):
                    continue
                entry = providers.setdefault(
                    provider_id,
                    {
                        "id": provider_id,
                        "name": str(item["provider_name"]),
                        "logo_url": self._image_url(item.get("logo_path"), size="w185"),
                        "availability": [],
                    },
                )
                entry["availability"].append(availability_type)
        return sorted(providers.values(), key=lambda item: item["name"].casefold())

    def provider_catalog(self, media_type: str, *, region: str = "US") -> list[dict]:
        if media_type not in {"movie", "tv"}:
            raise MediaIntegrationError("Provider catalog needs a movie or series.")
        payload = self._request(f"/watch/providers/{media_type}", {"watch_region": region})
        return [
            {
                "id": int(item["provider_id"]),
                "name": str(item["provider_name"]),
                "logo_url": self._image_url(item.get("logo_path"), size="w185"),
            }
            for item in payload.get("results") or []
            if item.get("provider_id") and item.get("provider_name")
        ]

    def genres(self, media_type: str) -> list[dict[str, Any]]:
        if media_type not in {"movie", "tv"}:
            raise MediaIntegrationError("Genre media type must be movie or series.")
        payload = self._request(f"/genre/{media_type}/list", {"language": "en-US"})
        return [
            {"id": int(item["id"]), "name": str(item["name"])}
            for item in payload.get("genres") or []
            if item.get("id") and item.get("name")
        ]

    def details(self, media_type: str, tmdb_id: int) -> dict:
        if media_type not in {"movie", "tv"}:
            raise MediaIntegrationError("Media type must be movie or series.")
        payload = self._request(
            f"/{media_type}/{int(tmdb_id)}",
            {
                "language": "en-US",
                "append_to_response": (
                    "credits,external_ids,videos,recommendations,similar,reviews,release_dates"
                ),
            },
        )
        item = self._summary(payload, media_type)
        credits = payload.get("credits") or {}
        external_ids = payload.get("external_ids") or {}
        item.update(
            {
                "runtime_minutes": self._runtime(payload, media_type),
                "genres": [
                    {"name": str(genre.get("name"))}
                    for genre in payload.get("genres") or []
                    if genre.get("name")
                ],
                "directors": [
                    {"name": str(member.get("name"))}
                    for member in credits.get("crew") or []
                    if member.get("job") == "Director" and member.get("name")
                ],
                "cast": [
                    {
                        "name": str(member.get("name")),
                        "character": str(member.get("character") or ""),
                        "profile_url": self._image_url(member.get("profile_path"), size="w185"),
                    }
                    for member in (credits.get("cast") or [])[:12]
                    if member.get("name")
                ],
                "tmdb_detail": {
                    "backdrop_url": self._image_url(payload.get("backdrop_path"), size="w1280"),
                    "tagline": str(payload.get("tagline") or ""),
                    "original_language": str(payload.get("original_language") or ""),
                    "countries": [
                        str(country.get("name"))
                        for country in payload.get("production_countries") or []
                        if country.get("name")
                    ],
                    "certification": _tmdb_certification(payload, media_type),
                    "tmdb_rating": payload.get("vote_average"),
                    "trailers": _tmdb_trailers(payload),
                    "reviews": _tmdb_reviews(payload),
                    "similar": _tmdb_related(payload.get("similar") or {}, media_type),
                    "recommendations": _tmdb_related(
                        payload.get("recommendations") or {}, media_type
                    ),
                },
                "external_ids": {
                    "tmdb_id": str(payload["id"]),
                    "tmdb_type": media_type,
                    **(
                        {"imdb_id": str(external_ids["imdb_id"])}
                        if external_ids.get("imdb_id")
                        else {}
                    ),
                },
            }
        )
        if media_type == "tv":
            item["seasons"] = [
                self._season_summary(season)
                for season in payload.get("seasons") or []
                if int(
                    season.get("season_number")
                    if season.get("season_number") is not None
                    else -1
                ) >= 0
            ]
        return item

    def seasons(self, tmdb_id: int) -> list[dict]:
        return self.details("tv", tmdb_id).get("seasons", [])

    def episodes(self, tmdb_id: int, season_number: int) -> list[dict]:
        payload = self._request(
            f"/tv/{int(tmdb_id)}/season/{int(season_number)}",
            {"language": "en-US"},
        )
        return [
            {
                "tmdb_id": int(episode["id"]),
                "name": str(episode.get("name") or "Untitled episode"),
                "overview": str(episode.get("overview") or ""),
                "season_number": int(episode.get("season_number") or season_number),
                "episode_number": int(episode.get("episode_number") or 0),
                "air_date": episode.get("air_date"),
                "runtime_minutes": episode.get("runtime"),
                "still_url": self._image_url(episode.get("still_path"), size="w780"),
            }
            for episode in payload.get("episodes") or []
            if episode.get("id") and episode.get("episode_number")
        ]

    def episode(self, tmdb_id: int, season_number: int, episode_number: int) -> dict | None:
        for item in self.episodes(tmdb_id, season_number):
            if item["episode_number"] == int(episode_number):
                return item
        return None

    def release_queries(
        self,
        media_type: str,
        tmdb_id: int,
        *,
        season: int | None = None,
        episode: int | None = None,
    ) -> tuple[dict, list[str], dict[str, Any]]:
        details = self.details(media_type, tmdb_id)
        title_variants = _title_variants(details)
        if media_type == "movie":
            queries = [
                f"{title} {details.get('year') or ''}".strip() for title in title_variants
            ]
            queries.extend(title_variants)
            return details, _dedupe_strings(queries), {
                "media_type": media_type,
                "title_variants": title_variants,
                "year": details.get("year"),
            }

        if season and episode:
            episode_item = self.episode(tmdb_id, season, episode)
            episode_title = str((episode_item or {}).get("name") or "")
            codes = [
                f"S{season:02d}E{episode:02d}",
                f"{season}x{episode:02d}",
                f"Season {season} Episode {episode}",
            ]
            queries = []
            for title in title_variants:
                queries.extend(f"{title} {code}" for code in codes)
                if episode_title:
                    queries.append(f"{title} {episode_title}")
                queries.append(f"{title} Season {season}")
                queries.append(f"{title} S{season:02d}")
            return details, _dedupe_strings(queries), {
                "media_type": media_type,
                "title_variants": title_variants,
                "season": season,
                "episode": episode,
                "episode_title": episode_title,
                "episode_code": f"S{season:02d}E{episode:02d}",
                "alt_episode_code": f"{season}x{episode:02d}",
            }

        if season:
            queries = []
            for title in title_variants:
                queries.append(f"{title} S{season:02d}")
                queries.append(f"{title} Season {season}")
                queries.append(title)
            return details, _dedupe_strings(queries), {
                "media_type": media_type,
                "title_variants": title_variants,
                "season": season,
            }

        return details, title_variants, {
            "media_type": media_type,
            "title_variants": title_variants,
        }

    def release_search_plan(
        self,
        media_type: str,
        tmdb_id: int,
        *,
        season: int | None = None,
        episode: int | None = None,
    ) -> tuple[dict, list[dict[str, Any]], dict[str, Any]]:
        """Build a small, ordered, multilingual Jackett search cascade.

        The alias cache belongs to this provider instance, which is retained by
        the Flask app extension.  It keeps normal release searches to one TMDb
        alternative-titles request per title per day without persisting remote
        metadata in a user record.
        """
        details, identity = self.release_search_identity(media_type, tmdb_id)
        suffix = _release_query_suffix(
            media_type,
            year=identity.get("year"),
            season=season,
            episode=episode,
        )
        attempts: list[dict[str, Any]] = []
        if identity.get("imdb_id"):
            attempts.append(
                {
                    "kind": "imdb_id",
                    "label": "IMDb ID",
                    "query": str(identity["imdb_id"]),
                    "imdb_id": str(identity["imdb_id"]),
                    "year": identity.get("year"),
                }
            )
        attempts.append(
            {
                "kind": "tmdb_id",
                "label": "TMDb ID",
                "query": str(identity["tmdb_id"]),
                "tmdb_id": str(identity["tmdb_id"]),
                "year": identity.get("year"),
            }
        )
        title_steps = (
            ("native", "Original title", identity.get("native_aliases") or []),
            (
                "transliteration",
                "Transliterated title",
                identity.get("transliterated_aliases") or [],
            ),
            ("international", "International title", identity.get("international_aliases") or []),
            ("alternative", "Alternative title", (identity.get("alternative_aliases") or [])[:3]),
        )
        seen_titles: set[str] = set()
        for kind, label, aliases in title_steps:
            for alias in aliases:
                cleaned = " ".join(str(alias or "").split())
                key = _normalize_title(cleaned)
                if not key or key in seen_titles:
                    continue
                seen_titles.add(key)
                attempts.append(
                    {
                        "kind": kind,
                        "label": label,
                        "query": f"{cleaned}{suffix}",
                        "year": identity.get("year"),
                    }
                )
                # The first title in each tier is the deliberate cascade; extra
                # alternatives are reserved for TMDb-provided alias variants.
                if kind != "alternative":
                    break
        match_context = {
            "media_type": media_type,
            "tmdb_id": str(identity["tmdb_id"]),
            "imdb_id": str(identity.get("imdb_id") or ""),
            "year": identity.get("year"),
            "original_title": identity.get("original_title") or "",
            "native_aliases": list(identity.get("native_aliases") or []),
            "transliterated_aliases": list(identity.get("transliterated_aliases") or []),
            "international_aliases": list(identity.get("international_aliases") or []),
            "alternative_aliases": list(identity.get("alternative_aliases") or []),
            "title_variants": list(identity.get("title_variants") or []),
            "season": season,
            "episode": episode,
        }
        if season and episode:
            episode_item = self.episode(tmdb_id, season, episode)
            match_context.update(
                {
                    "episode_title": str((episode_item or {}).get("name") or ""),
                    "episode_code": f"S{season:02d}E{episode:02d}",
                    "alt_episode_code": f"{season}x{episode:02d}",
                }
            )
        return details, attempts, match_context

    def release_search_identity(self, media_type: str, tmdb_id: int) -> tuple[dict, dict[str, Any]]:
        if media_type not in {"movie", "tv"}:
            raise MediaIntegrationError("Media type must be movie or series.")
        key = (media_type, int(tmdb_id))
        cached = self._release_alias_cache.get(key)
        if cached and cached[0] > time.monotonic():
            details, identity = cached[1]["details"], cached[1]["identity"]
            return dict(details), dict(identity)

        details = self.details(media_type, tmdb_id)
        try:
            aliases_payload = self._request(f"/{media_type}/{int(tmdb_id)}/alternative_titles")
            alternative_titles = [
                str(item.get("title") or "").strip()
                for item in aliases_payload.get("titles") or []
                if isinstance(item, dict) and item.get("title")
            ]
        except MediaIntegrationError:
            # A title search remains useful if the optional alias endpoint is
            # temporarily unavailable.  Do not turn that into a total failure.
            alternative_titles = []
        identity = _release_search_identity(details, alternative_titles)
        payload = {"details": dict(details), "identity": dict(identity)}
        self._release_alias_cache[key] = (
            time.monotonic() + self.RELEASE_ALIAS_CACHE_TTL_SECONDS,
            payload,
        )
        return details, identity

    def _search_score(self, summary: dict, normalized_query: str, payload: dict) -> float:
        title = _normalize_title(summary.get("title"))
        original_title = _normalize_title(summary.get("original_title"))
        aliases = [_normalize_title(alias) for alias in summary.get("alternate_titles") or []]
        query_tokens = set(normalized_query.split())
        title_tokens = set(title.split())
        shared = len(query_tokens & title_tokens)
        score = shared * 24
        if title == normalized_query:
            score += 420
        elif original_title and original_title == normalized_query:
            score += 320
        elif normalized_query in aliases:
            score += 280
        elif title.startswith(normalized_query):
            score += 180
        elif any(alias.startswith(normalized_query) for alias in aliases if normalized_query):
            score += 160
        elif normalized_query and normalized_query in title:
            score += 120
        if query_tokens and query_tokens.issubset(title_tokens):
            score += 80
        if summary.get("media_type") == "tv":
            score += 20
        score += float(payload.get("popularity") or 0) / 10
        return score

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict:
        if not self.configured:
            raise MediaIntegrationError("TMDB credentials are not configured.")
        headers = {"Accept": "application/json"}
        request_params = dict(params or {})
        if self.read_access_token:
            headers["Authorization"] = f"Bearer {self.read_access_token}"
        else:
            request_params["api_key"] = self.api_key
        try:
            response = self.session.get(
                f"https://api.themoviedb.org/3{path}",
                params=request_params,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise MediaIntegrationError("TMDB is unavailable.") from exc
        if not isinstance(payload, dict):
            raise MediaIntegrationError("TMDB returned an invalid response.")
        return payload

    def _summary(self, item: dict, media_type: str) -> dict:
        released = item.get("release_date") if media_type == "movie" else item.get(
            "first_air_date"
        )
        year = int(str(released)[:4]) if str(released)[:4].isdigit() else None
        return {
            "tmdb_id": int(item["id"]),
            "media_type": media_type,
            "type_label": "Movie" if media_type == "movie" else "Series",
            "title": str(item.get("title") or item.get("name") or "Untitled"),
            "original_title": str(
                item.get("original_title") or item.get("original_name") or ""
            ),
            "original_language": str(item.get("original_language") or ""),
            "overview": str(item.get("overview") or ""),
            "year": year,
            "release_date": released,
            "poster_url": self._image_url(item.get("poster_path")),
            "backdrop_url": self._image_url(item.get("backdrop_path"), size="w1280"),
            "rating": item.get("vote_average"),
        }

    def _season_summary(self, season: dict) -> dict:
        return {
            "tmdb_id": int(season["id"]),
            "name": str(season.get("name") or "Season"),
            "season_number": int(season.get("season_number") or 0),
            "episode_count": int(season.get("episode_count") or 0),
            "air_date": season.get("air_date"),
            "poster_url": self._image_url(season.get("poster_path")),
        }

    @staticmethod
    def _runtime(payload: dict, media_type: str) -> int | None:
        if media_type == "movie":
            return _optional_int(payload.get("runtime"))
        runtimes = payload.get("episode_run_time") or []
        return _optional_int(runtimes[0]) if runtimes else None

    @staticmethod
    def _image_url(path: str | None, *, size: str = "w500") -> str:
        return f"https://image.tmdb.org/t/p/{size}{path}" if path else ""


def _tmdb_certification(payload: dict, media_type: str) -> str:
    if media_type != "movie":
        return ""
    for country in payload.get("release_dates", {}).get("results") or []:
        releases = country.get("release_dates") or []
        certification = next(
            (
                str(item.get("certification") or "").strip()
                for item in releases
                if item.get("certification")
            ),
            "",
        )
        if certification and country.get("iso_3166_1") == "US":
            return certification
    return ""


def _tmdb_trailers(payload: dict) -> list[dict[str, str]]:
    return [
        {
            "name": str(video.get("name") or "Trailer"),
            "url": f"https://www.youtube.com/watch?v={video['key']}",
            "official": bool(video.get("official")),
        }
        for video in payload.get("videos", {}).get("results") or []
        if video.get("site") == "YouTube"
        and video.get("type") == "Trailer"
        and video.get("key")
    ][:4]


def _tmdb_reviews(payload: dict) -> list[dict[str, str]]:
    return [
        {
            "author": str(review.get("author") or "TMDB member"),
            "content": str(review.get("content") or "")[:1600],
            "url": str(review.get("url") or ""),
        }
        for review in payload.get("reviews", {}).get("results") or []
        if str(review.get("content") or "").strip()
    ][:3]


def _tmdb_related(payload: dict, media_type: str) -> list[dict[str, Any]]:
    return [
        {
            "tmdb_id": int(item["id"]),
            "media_type": media_type,
            "title": str(item.get("title") or item.get("name") or "Untitled"),
            "year": _optional_int(
                str(item.get("release_date") or item.get("first_air_date") or "")[:4]
            ),
            "poster_url": TmdbCatalogProvider._image_url(item.get("poster_path")),
            "rating": item.get("vote_average"),
        }
        for item in payload.get("results") or []
        if item.get("id")
    ][:12]


class JackettReleaseProvider:
    CAPABILITIES_CACHE_TTL_SECONDS = 15 * 60
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        min_seeders: int = 5,
        session: requests.Session | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.api_key = api_key.strip()
        self.min_seeders = max(0, int(min_seeders))
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self._capabilities_cache: tuple[float, set[str]] | None = None

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def search(self, query: str, media_type: str = "all", *, limit: int = 50) -> list[dict]:
        return self.search_many([query], media_type, limit=limit)

    def search_many(
        self,
        queries: list[str],
        media_type: str = "all",
        *,
        match_context: dict[str, Any] | None = None,
        mode: str = "auto",
        limit: int = 50,
    ) -> list[dict]:
        if not self.configured:
            raise MediaIntegrationError("Jackett is not configured.")
        categories = {"movie": "2000", "tv": "5000"}.get(media_type, "2000,5000")
        try:
            rows: list[dict] = []
            for query in _dedupe_strings(queries)[:6]:
                if len(query) < 2:
                    continue
                response = self.session.get(
                    urljoin(self.base_url, "api/v2.0/indexers/all/results"),
                    params={"apikey": self.api_key, "Query": query, "Category": categories},
                    headers={"Accept": "application/json"},
                    timeout=self.timeout_seconds,
                )
                if not response.ok:
                    raise MediaIntegrationError(
                        f"Jackett returned HTTP {response.status_code}."
                    )
                rows.extend(self._parse_json(response.json()))
            return self._filter(rows, limit, match_context=match_context, mode=mode)
        except (requests.RequestException, ValueError) as exc:
            raise MediaIntegrationError("Jackett is unavailable.") from exc

    def search_plan(
        self,
        attempts: list[dict[str, Any]],
        media_type: str,
        *,
        match_context: dict[str, Any] | None = None,
        mode: str = "auto",
        limit: int = 50,
    ) -> tuple[list[dict], list[dict[str, Any]]]:
        """Run the ordered release cascade and record only safe diagnostics."""
        if not self.configured:
            raise MediaIntegrationError("Jackett is not configured.")
        categories = {"movie": "2000", "tv": "5000"}.get(media_type, "2000,5000")
        capabilities = self.capabilities(media_type)
        rows: list[dict] = []
        diagnostics: list[dict[str, Any]] = []
        for attempt in attempts:
            kind = str(attempt.get("kind") or "title")
            query = str(attempt.get("query") or "").strip()
            if kind in {"imdb_id", "tmdb_id"} and kind not in capabilities:
                diagnostics.append(
                    {
                        "kind": kind,
                        "label": str(attempt.get("label") or kind),
                        "query": query,
                        "status": "skipped_unsupported",
                    }
                )
                continue
            if kind not in {"imdb_id", "tmdb_id"} and len(query) < 2:
                continue
            try:
                if kind in {"imdb_id", "tmdb_id"}:
                    found = self._search_identifier(attempt, media_type)
                else:
                    found = self._search_title(query, categories)
            except (requests.RequestException, ValueError) as exc:
                raise MediaIntegrationError("Jackett is unavailable.") from exc
            rows.extend(found)
            candidates = self._filter(rows, limit, match_context=match_context, mode=mode)
            diagnostics.append(
                {
                    "kind": kind,
                    "label": str(attempt.get("label") or kind),
                    "query": query,
                    "status": "completed",
                    "result_count": len(found),
                }
            )
            # Five well-matched candidates are enough for a useful chooser.
            # Avoid sending every spelling variant to every indexer needlessly.
            if len([item for item in candidates if item.get("match_score", 0) >= 135]) >= 5:
                break
        return self._filter(rows, limit, match_context=match_context, mode=mode), diagnostics

    def capabilities(self, media_type: str) -> set[str]:
        """Return ID search fields advertised by Jackett's aggregate caps.

        Aggregate caps do not prove every indexer supports a field, so callers
        still retain the title cascade as a portable fallback.
        """
        if self._capabilities_cache and self._capabilities_cache[0] > time.monotonic():
            return set(self._capabilities_cache[1])
        supported: set[str] = set()
        search_mode = "movie-search" if media_type == "movie" else "tv-search"
        try:
            response = self.session.get(
                urljoin(self.base_url, "api/v2.0/indexers/all/results/torznab/api"),
                params={"apikey": self.api_key, "t": "caps"},
                headers={"Accept": "application/xml"},
                timeout=self.timeout_seconds,
            )
            if response.ok:
                root = ET.fromstring(response.content)
                for node in root.iter():
                    if node.tag.rsplit("}", 1)[-1] != search_mode:
                        continue
                    for value in str(node.attrib.get("supportedParams") or "").split(","):
                        normalized = value.strip().casefold()
                        if normalized == "imdbid":
                            supported.add("imdb_id")
                        elif normalized == "tmdbid":
                            supported.add("tmdb_id")
        except (requests.RequestException, ET.ParseError, AttributeError):
            # Caps are an optimization.  A broken/stale caps response must not
            # block the ordinary title search that previously worked.
            pass
        self._capabilities_cache = (
            time.monotonic() + self.CAPABILITIES_CACHE_TTL_SECONDS,
            supported,
        )
        return supported

    def _search_title(self, query: str, categories: str) -> list[dict]:
        response = self.session.get(
            urljoin(self.base_url, "api/v2.0/indexers/all/results"),
            params={"apikey": self.api_key, "Query": query, "Category": categories},
            headers={"Accept": "application/json"},
            timeout=self.timeout_seconds,
        )
        if not response.ok:
            raise MediaIntegrationError(f"Jackett returned HTTP {response.status_code}.")
        return self._parse_json(response.json())

    def _search_identifier(self, attempt: dict[str, Any], media_type: str) -> list[dict]:
        params: dict[str, Any] = {
            "apikey": self.api_key,
            "t": "movie" if media_type == "movie" else "tvsearch",
        }
        if attempt.get("imdb_id"):
            params["imdbid"] = str(attempt["imdb_id"])
        if attempt.get("tmdb_id"):
            params["tmdbid"] = str(attempt["tmdb_id"])
        if attempt.get("year"):
            params["year"] = int(attempt["year"])
        response = self.session.get(
            urljoin(self.base_url, "api/v2.0/indexers/all/results/torznab/api"),
            params=params,
            headers={"Accept": "application/xml"},
            timeout=self.timeout_seconds,
        )
        if not response.ok:
            raise MediaIntegrationError(f"Jackett returned HTTP {response.status_code}.")
        return self._parse_torznab(response.content)

    @staticmethod
    def _parse_json(payload: Any) -> list[dict]:
        rows = payload.get("Results", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("Unexpected Jackett response")
        results = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            magnet = row.get("MagnetUri") or row.get("MagnetURI")
            if not magnet and str(row.get("Link") or "").startswith("magnet:?"):
                magnet = row["Link"]
            results.append(
                {
                    "magnet_uri": str(magnet or ""),
                    "title": str(row.get("Title") or "Untitled release"),
                    "seeders": _integer(row.get("Seeders")),
                    "leechers": _integer(row.get("Peers") or row.get("Leechers")),
                    "size": _integer(row.get("Size")),
                    "tracker": str(
                        row.get("Tracker") or row.get("TrackerId") or "Unknown tracker"
                    ),
                    "published": row.get("PublishDate") or row.get("FirstSeen"),
                    "imdb_id": _external_identifier(
                        row, "Imdb", "ImdbId", "IMDB", "IMDBId"
                    ),
                    "tmdb_id": _external_identifier(row, "Tmdb", "TmdbId", "TMDb", "TMDbId"),
                }
            )
        return results

    @staticmethod
    def _parse_torznab(payload: bytes) -> list[dict]:
        root = ET.fromstring(payload)
        results = []
        for item in root.iter():
            if item.tag.rsplit("}", 1)[-1] != "item":
                continue
            attributes = {
                str(node.attrib.get("name") or "").casefold(): str(node.attrib.get("value") or "")
                for node in item
                if node.tag.rsplit("}", 1)[-1] == "attr"
            }
            link = str(item.findtext("link") or "")
            magnet = link if link.startswith("magnet:?") else ""
            results.append(
                {
                    "magnet_uri": magnet,
                    "title": str(item.findtext("title") or "Untitled release"),
                    "seeders": _integer(attributes.get("seeders")),
                    "leechers": _integer(attributes.get("peers")),
                    "size": _integer(attributes.get("size")),
                    "tracker": attributes.get("tracker") or "Unknown tracker",
                    "published": item.findtext("pubDate") or "",
                    "imdb_id": attributes.get("imdb") or attributes.get("imdbid") or "",
                    "tmdb_id": attributes.get("tmdb") or attributes.get("tmdbid") or "",
                }
            )
        return results

    def _filter(
        self,
        rows: list[dict],
        limit: int,
        *,
        match_context: dict[str, Any] | None = None,
        mode: str = "auto",
    ) -> list[dict]:
        unique: dict[str, dict] = {}
        result_identities: dict[tuple[str, str, int], str] = {}
        for row in rows:
            magnet = str(row.get("magnet_uri") or "")
            if not magnet.startswith("magnet:?") or row.get("seeders", 0) < self.min_seeders:
                continue
            info_hash = _magnet_info_hash(magnet)
            key = info_hash or magnet.split("&", 1)[0].casefold()
            result_identity = _release_result_identity(row)
            existing_key = result_identities.get(result_identity)
            if existing_key and existing_key != key:
                previous = unique.get(existing_key)
                if previous is not None and previous["seeders"] >= row["seeders"]:
                    continue
                unique.pop(existing_key, None)
            result_identities[result_identity] = key
            previous = unique.get(key)
            if previous is None or row["seeders"] > previous["seeders"]:
                unique[key] = row
        ranked = []
        for row in unique.values():
            score, match_kind = self._release_score(row, match_context or {})
            ranked.append((score, match_kind, row))
        ranked.sort(
            key=lambda item: (-item[0], -item[2]["seeders"], item[2]["title"].casefold())
        )
        exact = [item for item in ranked if item[1] == "exact_episode"]
        season_pack = [item for item in ranked if item[1] == "season_pack"]
        general = [item for item in ranked if item[0] > 0 and item[1] == "general"]
        if mode == "season_pack":
            ranked = season_pack
        elif mode == "exact_episode" or exact:
            ranked = exact
        elif season_pack:
            ranked = season_pack + general
        else:
            ranked = [
                item
                for item in ranked
                if item[0] > -250 and item[1] != "unrelated"
            ]
        results = []
        for score, match_kind, row in ranked[: max(1, min(int(limit), 100))]:
            profile = _release_profile(row)
            results.append(
                {
                    **row,
                    "match_kind": match_kind,
                    "match_score": int(score),
                    "quality_label": profile["quality_label"],
                    "codec_label": profile["codec_label"],
                    "playback_label": profile["playback_label"],
                    "subtitle_label": profile["subtitle_label"],
                    "release_tags": profile["tags"],
                }
            )
        return results

    def _release_score(
        self, row: dict, match_context: dict[str, Any]
    ) -> tuple[float, str]:
        title = _normalize_title(row.get("title"))
        score = float(row.get("seeders") or 0) * 12
        score += _release_profile(row)["score_adjustment"]
        match_kind = "general"
        title_score, title_strength = _release_title_match_score(title, match_context)
        score += title_score
        row_imdb_id = str(row.get("imdb_id") or "").casefold()
        row_tmdb_id = str(row.get("tmdb_id") or "")
        if row_imdb_id and row_imdb_id == str(match_context.get("imdb_id") or "").casefold():
            score += 100
            title_strength = max(title_strength, 2)
        if row_tmdb_id and row_tmdb_id == str(match_context.get("tmdb_id") or ""):
            score += 100
            title_strength = max(title_strength, 2)
        if match_context.get("title_variants") and not title_strength:
            return score - 1000, "unrelated"
        expected_year = _optional_int(match_context.get("year"))
        release_years = {int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", title)}
        if expected_year and expected_year in release_years:
            score += 25
        elif expected_year and release_years:
            score -= 50
        season = _optional_int(match_context.get("season"))
        episode = _optional_int(match_context.get("episode"))
        episode_code = str(match_context.get("episode_code") or "").casefold()
        alt_episode_code = str(match_context.get("alt_episode_code") or "").casefold()
        episode_title = _normalize_title(match_context.get("episode_title"))
        if season:
            season_tokens = (
                f"s{season:02d}",
                f"season {season}",
                f"{season}x",
            )
            has_season_ref = any(token in title for token in season_tokens)
        else:
            has_season_ref = False
        if episode and season:
            if episode_code and episode_code.casefold() in title:
                return score + 700, "exact_episode"
            if alt_episode_code and alt_episode_code.casefold() in title:
                return score + 660, "exact_episode"
            if episode_title and episode_title in title:
                score += 220
            if has_season_ref:
                score += 120
                if re.search(rf"\bs{season:02d}e\d{{2}}\b", title) and not re.search(
                    rf"\bs{season:02d}e{episode:02d}\b", title
                ):
                    return score - 700, "wrong_episode"
                if re.search(rf"\b{season}x\d{{2}}\b", title) and not re.search(
                    rf"\b{season}x{episode:02d}\b", title
                ):
                    return score - 680, "wrong_episode"
                if any(token in title for token in ("complete", "season pack", "season")):
                    match_kind = "season_pack"
                    score += 180
            elif re.search(r"\bs\d{2}\b", title):
                return score - 900, "wrong_season"
        elif season and has_season_ref:
            score += 180
            if (
                "complete" in title
                or "pack" in title
                or re.search(rf"\bs{season:02d}\b", title)
                or f"season {season}" in title
            ):
                match_kind = "season_pack"
                score += 260
            if title_strength == 2:
                score += 140
            if "complete series" in title or re.search(r"\bs\d{2}\s+\d\b", title):
                score -= 160
            size = _integer(row.get("size"))
            if 8 * 1024**3 <= size <= 40 * 1024**3:
                score += 90
            if 10 * 1024**3 <= size <= 25 * 1024**3:
                score += 80
        elif season and re.search(r"\bs\d{2}\b", title):
            return score - 900, "wrong_season"
        return score, match_kind


class NotionMovieProvider:
    VERSION = "2025-09-03"
    MOVIE_REQUIRED_PROPERTIES = {
        "TMDB ID": {"number": {}},
        "Media Type": {"select": {}},
        "Season": {"number": {}},
        "Episode": {"number": {}},
        "Release Title": {"rich_text": {}},
        "Magnet Link Used": {"rich_text": {}},
        "Watched": {"checkbox": {}},
        "Date Watched": {"date": {}},
    }
    TV_SHOW_REQUIRED_PROPERTIES = {
        "TMDB ID": {"number": {}},
        "Media Type": {"select": {}},
        "Overview": {"rich_text": {}},
        "Poster URL": {"url": {}},
        "Year": {"number": {}},
        "Total Seasons": {"number": {}},
        "Total Episodes": {"number": {}},
        "Completed Seasons": {"number": {}},
        "Watched Episodes": {"number": {}},
        "Next Episode": {"rich_text": {}},
        "Status": {"select": {}},
        "Last Synced": {"date": {}},
    }
    TV_EPISODE_REQUIRED_PROPERTIES = {
        "Show": {"relation": {}},
        "Show TMDB ID": {"number": {}},
        "Show Title": {"rich_text": {}},
        "Season": {"number": {}},
        "Episode": {"number": {}},
        "Episode Title": {"rich_text": {}},
        "Still URL": {"url": {}},
        "Runtime": {"number": {}},
        "Watched": {"checkbox": {}},
        "Progress Percent": {"number": {}},
        "Exact Magnet": {"rich_text": {}},
        "Fallback Season Pack Magnet": {"rich_text": {}},
        "Release Title": {"rich_text": {}},
        "Release Mode": {"select": {}},
        "Last Synced": {"date": {}},
    }

    def __init__(
        self,
        *,
        token: str,
        database_id: str = "",
        data_source_id: str = "",
        tv_show_database_id: str = "",
        tv_show_data_source_id: str = "",
        tv_episode_database_id: str = "",
        tv_episode_data_source_id: str = "",
        session: requests.Session | None = None,
        timeout_seconds: float = 20,
    ) -> None:
        self.token = token.strip()
        self.database_id = database_id.strip().replace("-", "")
        self._movie_data_source_id = data_source_id.strip().replace("-", "")
        self.tv_show_database_id = tv_show_database_id.strip().replace("-", "")
        self._tv_show_data_source_id = tv_show_data_source_id.strip().replace("-", "")
        self.tv_episode_database_id = tv_episode_database_id.strip().replace("-", "")
        self._tv_episode_data_source_id = tv_episode_data_source_id.strip().replace("-", "")
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self._schema_cache: dict[str, dict[str, dict]] = {}

    @property
    def configured(self) -> bool:
        return bool(
            self.token
            and (
                self.movie_configured
                or (self.tv_show_configured and self.tv_episode_configured)
            )
        )

    @property
    def movie_configured(self) -> bool:
        return bool(self.database_id or self._movie_data_source_id)

    @property
    def tv_show_configured(self) -> bool:
        return bool(self.tv_show_database_id or self._tv_show_data_source_id)

    @property
    def tv_episode_configured(self) -> bool:
        return bool(self.tv_episode_database_id or self._tv_episode_data_source_id)

    def _resolve_data_source_id(self, *, database_id: str, explicit_id: str) -> str:
        if explicit_id:
            return explicit_id
        if not database_id:
            raise MediaIntegrationError("The Notion database has no accessible data source.")
        payload = self._request("GET", f"/databases/{database_id}")
        sources = payload.get("data_sources") or []
        if not sources:
            raise MediaIntegrationError("The Notion database has no accessible data source.")
        return str(sources[0]["id"])

    @property
    def data_source_id(self) -> str:
        self._movie_data_source_id = self._resolve_data_source_id(
            database_id=self.database_id,
            explicit_id=self._movie_data_source_id,
        )
        return self._movie_data_source_id

    @property
    def tv_show_data_source_id(self) -> str:
        self._tv_show_data_source_id = self._resolve_data_source_id(
            database_id=self.tv_show_database_id,
            explicit_id=self._tv_show_data_source_id,
        )
        return self._tv_show_data_source_id

    @property
    def tv_episode_data_source_id(self) -> str:
        self._tv_episode_data_source_id = self._resolve_data_source_id(
            database_id=self.tv_episode_database_id,
            explicit_id=self._tv_episode_data_source_id,
        )
        return self._tv_episode_data_source_id

    def _kind_data_source_id(self, kind: str) -> str:
        if kind == "movie":
            return self.data_source_id
        if kind == "tv_show":
            return self.tv_show_data_source_id
        if kind == "tv_episode":
            return self.tv_episode_data_source_id
        raise MediaIntegrationError("Unsupported Notion schema kind.")

    def schema(self, *, kind: str = "movie", refresh: bool = False) -> dict[str, dict]:
        if refresh or kind not in self._schema_cache:
            payload = self._request("GET", f"/data_sources/{self._kind_data_source_id(kind)}")
            self._schema_cache[kind] = dict(payload.get("properties") or {})
        return self._schema_cache[kind]

    def _required_properties(self, kind: str) -> dict[str, dict]:
        if kind == "movie":
            return self.MOVIE_REQUIRED_PROPERTIES
        if kind == "tv_show":
            return self.TV_SHOW_REQUIRED_PROPERTIES
        if kind == "tv_episode":
            return {
                **self.TV_EPISODE_REQUIRED_PROPERTIES,
                "Show": {
                    "relation": {
                        "data_source_id": self.tv_show_data_source_id,
                        "type": "single_property",
                        "single_property": {},
                    }
                },
            }
        raise MediaIntegrationError("Unsupported Notion schema kind.")

    def ensure_writeback_schema(self, *, kind: str = "movie") -> None:
        schema = self.schema(kind=kind)
        missing = {
            name: definition
            for name, definition in self._required_properties(kind).items()
            if name not in schema
        }
        if not missing:
            return
        self._request(
            "PATCH",
            f"/data_sources/{self._kind_data_source_id(kind)}",
            json={"properties": missing},
        )
        self.schema(kind=kind, refresh=True)

    def consolidate_movie_completion_status(self) -> bool:
        """Replace the duplicate Finished option with the single Watched state."""
        schema = self.schema(kind="movie", refresh=True)
        definition = schema.get("Status") or {}
        property_type = str(definition.get("type") or "")
        if property_type not in {"status", "select"}:
            return False

        configuration = dict(definition.get(property_type) or {})
        options = list(configuration.get("options") or [])
        has_finished = any(
            str(option.get("name") or "").strip().casefold() == "finished"
            for option in options
        )
        if not has_finished:
            return False

        watched_option = next(
            (
                option
                for option in options
                if str(option.get("name") or "").strip().casefold() == "watched"
            ),
            None,
        )
        if watched_option is None:
            options.append({"name": "Watched", "color": "green"})

        for page in self._movie_pages_with_status("Finished", property_type):
            self._request(
                "PATCH",
                f"/pages/{str(page.get('id') or '').replace('-', '')}",
                json={"properties": {"Status": {property_type: {"name": "Watched"}}}},
            )

        retained_options = [
            option
            for option in options
            if str(option.get("name") or "").strip().casefold() != "finished"
        ]
        self._request(
            "PATCH",
            f"/data_sources/{self.data_source_id}",
            json={"properties": {"Status": {property_type: {"options": retained_options}}}},
        )
        self.schema(kind="movie", refresh=True)
        return True

    def _movie_pages_with_status(self, value: str, property_type: str) -> list[dict]:
        pages = []
        cursor = None
        while True:
            body: dict[str, Any] = {
                "page_size": 100,
                "filter": {"property": "Status", property_type: {"equals": value}},
            }
            if cursor:
                body["start_cursor"] = cursor
            payload = self._request(
                "POST",
                f"/data_sources/{self.data_source_id}/query",
                json=body,
            )
            pages.extend(payload.get("results") or [])
            cursor = payload.get("next_cursor")
            if not payload.get("has_more") or not cursor:
                break
        return [page for page in pages if not page.get("in_trash")]

    def movie_score_option_labels(self) -> list[str]:
        definition = self.schema(kind="movie").get("Score /5") or {}
        if definition.get("type") != "select":
            return []
        return [
            str(option.get("name") or "").strip()
            for option in (definition.get("select") or {}).get("options") or []
            if str(option.get("name") or "").strip()
        ]

    def _list_pages(self, data_source_id: str) -> list[dict]:
        pages = []
        cursor = None
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            payload = self._request("POST", f"/data_sources/{data_source_id}/query", json=body)
            pages.extend(payload.get("results") or [])
            cursor = payload.get("next_cursor")
            if not payload.get("has_more") or not cursor:
                break
        return [page for page in pages if not page.get("in_trash")]

    def list_items(self) -> list[dict]:
        if not self.configured:
            raise MediaIntegrationError("Notion is not configured.")
        items: list[dict] = []
        legacy_tv_items: list[dict] = []
        tv_tmdb_ids: set[int] = set()

        if self.movie_configured:
            for page in self._list_pages(self.data_source_id):
                item = self._movie_page_item(page)
                if item["media_type"] == "tv":
                    legacy_tv_items.append(item)
                else:
                    items.append(item)

        if self.tv_show_configured and self.tv_episode_configured:
            show_pages = [self._tv_show_page_item(page) for page in self._list_pages(self.tv_show_data_source_id)]
            episode_pages = [
                self._tv_episode_page_item(page) for page in self._list_pages(self.tv_episode_data_source_id)
            ]
            episodes_by_show: dict[int, list[dict]] = {}
            for episode in episode_pages:
                show_tmdb_id = int(episode.get("show_tmdb_id") or 0)
                if show_tmdb_id < 1:
                    continue
                episodes_by_show.setdefault(show_tmdb_id, []).append(episode)

            for show in show_pages:
                tmdb_id = int(show.get("tmdb_id") or 0)
                tv_tmdb_ids.add(tmdb_id)
                episode_items = sorted(
                    episodes_by_show.get(tmdb_id, []),
                    key=lambda item: (int(item.get("season") or 0), int(item.get("episode") or 0)),
                )
                seasons = self._season_summaries(show, episode_items)
                items.append(
                    {
                        **show,
                        "episode_items": episode_items,
                        "seasons": seasons,
                        "tv_total_seasons": len(seasons) or int(show.get("tv_total_seasons") or 0),
                        "tv_total_episodes": len(episode_items) or int(show.get("tv_total_episodes") or 0),
                        "tv_show_notion_page_id": show["notion_page_id"],
                        "tv_show_notion_url": show["notion_url"],
                    }
                )

        for item in legacy_tv_items:
            tmdb_id = int(item.get("tmdb_id") or 0)
            if tmdb_id and tmdb_id in tv_tmdb_ids:
                continue
            item["legacy_notion_page_id"] = item["notion_page_id"]
            items.append(item)

        return sorted(items, key=lambda item: (str(item.get("title") or "").casefold(), item.get("year") or 0))

    def upsert_media(
        self,
        media: dict,
        *,
        magnet_uri: str = "",
        release_title: str = "",
        season: int | None = None,
        episode: int | None = None,
        release_mode: str = "episode",
        status: str = "watching",
    ) -> dict:
        if (
            str(media.get("media_type") or "") == "tv"
            and self.tv_show_configured
            and self.tv_episode_configured
        ):
            return self._upsert_tv_media(
                media,
                magnet_uri=magnet_uri,
                release_title=release_title,
                season=season,
                episode=episode,
                release_mode=release_mode,
                status=status,
            )
        self.ensure_writeback_schema(kind="movie")
        tmdb_id = int(media["tmdb_id"])
        library_items = self.list_items()
        existing = next(
            (
                item
                for item in library_items
                if item.get("tmdb_id") == tmdb_id
                and item.get("media_type") == media["media_type"]
            ),
            None,
        )
        if existing is None:
            normalized = _normalize_title(media.get("title"))
            existing = next(
                (
                    item
                    for item in library_items
                    if _normalize_title(item.get("title")) == normalized
                    and item.get("year") == media.get("year")
                ),
                None,
            )
        properties = self._media_properties(
            media,
            magnet_uri=magnet_uri,
            release_title=release_title,
            season=season,
            episode=episode,
            status=status,
        )
        if existing:
            payload = self._request(
                "PATCH",
                f"/pages/{existing['notion_page_id']}",
                json={"properties": properties},
            )
        else:
            payload = self._request(
                "POST",
                "/pages",
                json={
                    "parent": {
                        "type": "data_source_id",
                        "data_source_id": self.data_source_id,
                    },
                    "properties": properties,
                },
            )
        return self._movie_page_item(payload)

    def _upsert_tv_media(
        self,
        media: dict,
        *,
        magnet_uri: str,
        release_title: str,
        season: int | None,
        episode: int | None,
        release_mode: str,
        status: str,
    ) -> dict:
        self.ensure_writeback_schema(kind="tv_show")
        self.ensure_writeback_schema(kind="tv_episode")
        show_page = self._upsert_tv_show_page(media, status=status)
        existing_episodes = self._existing_tv_episode_rows(int(media["tmdb_id"]))
        created_rows: list[dict] = []
        for season_key, rows in dict(media.get("episodes_by_season") or {}).items():
            season_number = int(str(season_key))
            for row in rows or []:
                created_rows.append(
                    self._upsert_tv_episode_page(
                        media,
                        show_page_id=show_page["notion_page_id"],
                        episode_data={**row, "season_number": row.get("season_number", season_number)},
                        existing=existing_episodes.get(
                            (
                                int(row.get("season_number") or season_number),
                                int(row.get("episode_number") or 0),
                            )
                        ),
                    )
                )

        selected_episode_page = None
        if season and episode:
            selected_episode_page = next(
                (
                    row
                    for row in created_rows
                    if int(row.get("season") or 0) == int(season)
                    and int(row.get("episode") or 0) == int(episode)
                ),
                existing_episodes.get((int(season), int(episode))),
            )
            if selected_episode_page:
                values = {
                    "Release Title": release_title,
                    "Release Mode": "Season pack fallback" if release_mode == "season_pack" else "Exact episode",
                }
                if magnet_uri:
                    if release_mode == "season_pack":
                        values["Fallback Season Pack Magnet"] = magnet_uri
                    else:
                        values["Exact Magnet"] = magnet_uri
                self._request(
                    "PATCH",
                    f"/pages/{selected_episode_page['notion_page_id']}",
                    json={"properties": self._properties(values, kind="tv_episode")},
                )

        refreshed_show = self._existing_tv_show(int(media["tmdb_id"])) or show_page
        refreshed_episodes = sorted(
            self._existing_tv_episode_rows(int(media["tmdb_id"])).values(),
            key=lambda item: (int(item.get("season") or 0), int(item.get("episode") or 0)),
        )
        seasons = self._season_summaries(refreshed_show, refreshed_episodes)
        return {
            **refreshed_show,
            "episode_items": refreshed_episodes,
            "seasons": seasons,
            "tv_total_seasons": len(seasons) or int(refreshed_show.get("tv_total_seasons") or 0),
            "tv_total_episodes": len(refreshed_episodes) or int(refreshed_show.get("tv_total_episodes") or 0),
            "tv_show_notion_page_id": refreshed_show["notion_page_id"],
            "tv_show_notion_url": refreshed_show["notion_url"],
            "selected_episode_page_id": str((selected_episode_page or {}).get("notion_page_id") or ""),
        }

    def _existing_tv_show(self, tmdb_id: int) -> dict | None:
        if not (self.tv_show_configured and self.tv_episode_configured):
            return None
        for page in self._list_pages(self.tv_show_data_source_id):
            item = self._tv_show_page_item(page)
            if int(item.get("tmdb_id") or 0) == int(tmdb_id):
                return item
        return None

    def _existing_tv_episode_rows(self, tmdb_id: int) -> dict[tuple[int, int], dict]:
        rows: dict[tuple[int, int], dict] = {}
        if not (self.tv_show_configured and self.tv_episode_configured):
            return rows
        for page in self._list_pages(self.tv_episode_data_source_id):
            item = self._tv_episode_page_item(page)
            if int(item.get("show_tmdb_id") or 0) != int(tmdb_id):
                continue
            rows[(int(item.get("season") or 0), int(item.get("episode") or 0))] = item
        return rows

    def _upsert_tv_show_page(self, media: dict, *, status: str) -> dict:
        existing = self._existing_tv_show(int(media["tmdb_id"]))
        properties = self._tv_show_properties(media, status=status)
        if existing:
            payload = self._request(
                "PATCH",
                f"/pages/{existing['notion_page_id']}",
                json={"properties": properties},
            )
        else:
            payload = self._request(
                "POST",
                "/pages",
                json={
                    "parent": {"type": "data_source_id", "data_source_id": self.tv_show_data_source_id},
                    "properties": properties,
                },
            )
        return self._tv_show_page_item(payload)

    def _upsert_tv_episode_page(
        self,
        media: dict,
        *,
        show_page_id: str,
        episode_data: dict,
        existing: dict | None,
    ) -> dict:
        properties = self._tv_episode_properties(
            media,
            show_page_id=show_page_id,
            episode_data=episode_data,
            existing=existing,
        )
        if existing:
            payload = self._request(
                "PATCH",
                f"/pages/{existing['notion_page_id']}",
                json={"properties": properties},
            )
        else:
            payload = self._request(
                "POST",
                "/pages",
                json={
                    "parent": {"type": "data_source_id", "data_source_id": self.tv_episode_data_source_id},
                    "properties": properties,
                },
            )
        return self._tv_episode_page_item(payload)

    def mark_watched(self, notion_page_id: str, *, started: bool = False) -> None:
        self.ensure_writeback_schema(kind="movie")
        now = datetime.now(timezone.utc).isoformat()
        values = (
            {"watching history": now, "Status": "Not finished"}
            if started
            else {
                "Watched": True,
                "Date Watched": now,
                "finishing history": now,
                "Status": "Watched",
            }
        )
        properties = self._properties(values, kind="movie")
        if properties:
            self._request(
                "PATCH",
                f"/pages/{notion_page_id.replace('-', '')}",
                json={"properties": properties},
            )

    def set_score(self, notion_page_id: str, score_label: str | None) -> None:
        properties = self._properties({"Score /5": score_label}, kind="movie")
        if properties:
            self._request(
                "PATCH",
                f"/pages/{notion_page_id.replace('-', '')}",
                json={"properties": properties},
            )

    def _media_properties(
        self,
        media: dict,
        *,
        magnet_uri: str,
        release_title: str,
        season: int | None,
        episode: int | None,
        status: str,
    ) -> dict:
        media_type = str(media["media_type"])
        notion_status = {
            "want_to_watch": "Want to watch",
            "watching": "Not finished",
            # Notion has one completed state.  Keep accepting the legacy
            # internal value, but never write a separate "Finished" option.
            "finished": "Watched",
            "watched": "Watched",
        }.get(status, "Not finished")
        values = {
            "Name": media.get("title"),
            "TMDB ID": media.get("tmdb_id"),
            "Media Type": "Movie" if media_type == "movie" else "Series",
            "Year": media.get("year"),
            "Overview": media.get("overview"),
            "Poster URL": media.get("poster_url"),
            "Rating": media.get("rating"),
            "Director": _names_text(media.get("directors")),
            "Director Entry": _names_text(media.get("directors")),
            "category": "movie" if media_type == "movie" else "TV Show",
            "source": "Dragon",
            "Season": season,
            "Episode": episode,
            "Watched": status == "watched",
            "Status": notion_status,
        }
        if magnet_uri:
            values["Magnet FHD"] = magnet_uri
            values["Magnet Link Used"] = magnet_uri
        if release_title:
            values["Release Title"] = release_title
        return self._properties(values, kind="movie")

    def _tv_show_properties(self, media: dict, *, status: str) -> dict:
        seasons = [item for item in list(media.get("seasons") or []) if int(item.get("season_number") or 0) > 0]
        total_episodes = sum(int(item.get("episode_count") or 0) for item in seasons)
        values = {
            "Name": media.get("title"),
            "TMDB ID": media.get("tmdb_id"),
            "Media Type": "Series",
            "Overview": media.get("overview"),
            "Poster URL": media.get("poster_url"),
            "Year": media.get("year"),
            "Total Seasons": len(seasons),
            "Total Episodes": total_episodes,
            "Completed Seasons": media.get("completed_seasons_count"),
            "Watched Episodes": media.get("watched_episodes_count"),
            "Next Episode": media.get("next_episode_label"),
            "Status": {
                "want_to_watch": "Want to watch",
                "watching": "Watching",
                "finished": "Finished",
                "watched": "Watched",
            }.get(status, "Watching"),
            "Last Synced": datetime.now(timezone.utc).date().isoformat(),
        }
        return self._properties(values, kind="tv_show")

    def _tv_episode_properties(
        self,
        media: dict,
        *,
        show_page_id: str,
        episode_data: dict,
        existing: dict | None,
    ) -> dict:
        season_number = int(episode_data.get("season_number") or 0)
        episode_number = int(episode_data.get("episode_number") or 0)
        values = {
            "Name": f"{media.get('title')} S{season_number:02d}E{episode_number:02d}",
            "Show": {"page_ids": [show_page_id]},
            "Show TMDB ID": media.get("tmdb_id"),
            "Show Title": media.get("title"),
            "Season": season_number,
            "Episode": episode_number,
            "Episode Title": episode_data.get("name"),
            "Still URL": episode_data.get("still_url"),
            "Runtime": episode_data.get("runtime_minutes") or episode_data.get("runtime"),
            "Watched": bool((existing or {}).get("watched")),
            "Progress Percent": (existing or {}).get("progress_percent"),
            "Exact Magnet": (existing or {}).get("exact_magnet"),
            "Fallback Season Pack Magnet": (existing or {}).get("fallback_magnet"),
            "Release Title": (existing or {}).get("release_title"),
            "Release Mode": (existing or {}).get("release_mode"),
            "Last Synced": datetime.now(timezone.utc).date().isoformat(),
        }
        return self._properties(values, kind="tv_episode")

    def _properties(self, values: dict[str, Any], *, kind: str) -> dict:
        schema = self.schema(kind=kind)
        properties = {}
        for name, value in values.items():
            definition = schema.get(name)
            if not definition:
                continue
            if definition.get("type") == "relation" and isinstance(value, dict) and value.get("page_ids"):
                encoded = {"relation": [{"id": page_id} for page_id in value["page_ids"]]}
            else:
                encoded = (
                    self._relation_property(definition, value)
                    if definition.get("type") == "relation"
                    else _encode_notion_property(definition.get("type"), value)
                )
            if encoded is not None:
                properties[name] = encoded
        return properties

    def _relation_property(self, definition: dict, value: Any) -> dict | None:
        names = _names(value)
        if not names:
            return {"relation": []}
        relation = definition.get("relation") or {}
        target_id = str(
            relation.get("data_source_id")
            or relation.get("database_id")
            or relation.get("synced_property_id")
            or ""
        ).replace("-", "")
        if not target_id:
            return None
        page_ids = [
            page_id
            for name in names
            if (page_id := self._find_or_create_relation_page(target_id, name))
        ]
        if not page_ids:
            return None
        return {"relation": [{"id": page_id} for page_id in page_ids]}

    def _find_or_create_relation_page(self, data_source_id: str, title: str) -> str:
        target_schema = self._request("GET", f"/data_sources/{data_source_id}").get(
            "properties"
        ) or {}
        title_property = next(
            (
                name
                for name, definition in target_schema.items()
                if definition.get("type") == "title"
            ),
            "Name",
        )
        payload = self._request(
            "POST",
            f"/data_sources/{data_source_id}/query",
            json={
                "page_size": 10,
                "filter": {
                    "property": title_property,
                    "title": {"equals": title},
                },
            },
        )
        for page in payload.get("results") or []:
            if page.get("in_trash"):
                continue
            page_title = _decode_notion_property(
                (page.get("properties") or {}).get(title_property)
            )
            if _normalize_title(page_title) == _normalize_title(title):
                return str(page.get("id") or "")
        created = self._request(
            "POST",
            "/pages",
            json={
                "parent": {"type": "data_source_id", "data_source_id": data_source_id},
                "properties": {
                    title_property: {
                        "title": [{"type": "text", "text": {"content": title}}]
                    }
                },
            },
        )
        return str(created.get("id") or "")

    def _movie_page_item(self, page: dict) -> dict:
        properties = page.get("properties") or {}
        category = str(_decode_notion_property(properties.get("category")) or "")
        media_type_value = str(
            _decode_notion_property(properties.get("Media Type")) or ""
        ).casefold()
        media_type = (
            "tv"
            if media_type_value in {"series", "tv", "show"}
            or any(token in category.casefold() for token in ("tv", "series", "anime"))
            else "movie"
        )
        raw_score = _decode_notion_property(properties.get("Score /5"))
        score_option = score_option_for_input(
            raw_score,
            labels=self.movie_score_option_labels() or [option.label for option in notion_score_options()],
        )
        status = _notion_status(_decode_notion_property(properties.get("Status")))
        watched = bool(_decode_notion_property(properties.get("Watched")))
        if watched:
            status = "watched"
        return {
            "notion_page_id": str(page.get("id") or ""),
            "notion_url": page.get("url"),
            "last_edited_time": page.get("last_edited_time"),
            "title": str(_decode_notion_property(properties.get("Name")) or "Untitled"),
            "year": _optional_int(_decode_notion_property(properties.get("Year"))),
            "media_type": media_type,
            "tmdb_id": _optional_int(
                _decode_notion_property(properties.get("TMDB ID"))
            ),
            "overview": str(
                _decode_notion_property(properties.get("Overview")) or ""
            ),
            "poster_url": str(
                _decode_notion_property(properties.get("Poster URL"))
                or _decode_notion_property(properties.get("poster "))
                or ""
            ),
            "category": category or ("movie" if media_type == "movie" else "TV Show"),
            "source": str(
                _decode_notion_property(properties.get("source")) or "Notion"
            ),
            "status": status,
            "personal_score": score_option.value if score_option else _select_number(raw_score),
            "personal_score_label": score_option.label if score_option else None,
            "genres": _named_values(
                _decode_notion_property(properties.get("Genres"))
            ),
            "directors": _named_values(
                _decode_notion_property(properties.get("Director"))
            ),
            "season": _optional_int(
                _decode_notion_property(properties.get("Season"))
            ),
            "episode": _optional_int(
                _decode_notion_property(properties.get("Episode"))
            ),
            "release_title": str(
                _decode_notion_property(properties.get("Release Title")) or ""
            ),
            "watched": watched,
            "date_watched": _decode_notion_property(properties.get("Date Watched")),
            "playback_sources": [
                value
                for value in (
                    _source_value(
                        properties, "Magnet Link Used", "magnet", "Selected magnet"
                    ),
                    _source_value(properties, "Magnet FHD", "magnet", "FHD magnet"),
                    _source_value(properties, "Magnet HD", "magnet", "HD magnet"),
                    _source_value(properties, "Torrent FHD", "torrent", "FHD torrent"),
                    _source_value(properties, "Torrent HD", "torrent", "HD torrent"),
                )
                if value
            ],
        }

    def _tv_show_page_item(self, page: dict) -> dict:
        properties = page.get("properties") or {}
        return {
            "notion_page_id": str(page.get("id") or ""),
            "notion_url": page.get("url"),
            "last_edited_time": page.get("last_edited_time"),
            "title": str(_decode_notion_property(properties.get("Name")) or "Untitled"),
            "year": _optional_int(_decode_notion_property(properties.get("Year"))),
            "media_type": "tv",
            "tmdb_id": _optional_int(_decode_notion_property(properties.get("TMDB ID"))),
            "overview": str(_decode_notion_property(properties.get("Overview")) or ""),
            "poster_url": str(_decode_notion_property(properties.get("Poster URL")) or ""),
            "category": "TV Show",
            "source": "Notion",
            "status": _notion_status(_decode_notion_property(properties.get("Status"))),
            "tv_total_seasons": _optional_int(_decode_notion_property(properties.get("Total Seasons"))) or 0,
            "tv_total_episodes": _optional_int(_decode_notion_property(properties.get("Total Episodes"))) or 0,
            "completed_seasons_count": _optional_int(_decode_notion_property(properties.get("Completed Seasons"))) or 0,
            "watched_episodes_count": _optional_int(_decode_notion_property(properties.get("Watched Episodes"))) or 0,
            "next_episode_label": str(_decode_notion_property(properties.get("Next Episode")) or ""),
            "playback_sources": [],
        }

    def _tv_episode_page_item(self, page: dict) -> dict:
        properties = page.get("properties") or {}
        notion_page_id = str(page.get("id") or "")
        season = _optional_int(_decode_notion_property(properties.get("Season")))
        episode = _optional_int(_decode_notion_property(properties.get("Episode")))
        exact_magnet = str(_decode_notion_property(properties.get("Exact Magnet")) or "").strip()
        fallback_magnet = str(
            _decode_notion_property(properties.get("Fallback Season Pack Magnet")) or ""
        ).strip()
        release_title = str(_decode_notion_property(properties.get("Release Title")) or "")
        items = []
        if exact_magnet:
            items.append(
                {
                    "kind": "magnet",
                    "label": f"S{int(season or 0):02d}E{int(episode or 0):02d} Jackett magnet",
                    "locator": exact_magnet,
                    "selected": True,
                    "season": season,
                    "episode": episode,
                    "source_role": "exact_episode",
                    "metadata": {
                        "origin": "notion",
                        "release_mode": "episode",
                        "season": season,
                        "episode": episode,
                        "episode_notion_page_id": notion_page_id,
                        "release_title": release_title,
                    },
                }
            )
        if fallback_magnet:
            items.append(
                {
                    "kind": "magnet",
                    "label": f"S{int(season or 0):02d} season pack Jackett magnet",
                    "locator": fallback_magnet,
                    "selected": not exact_magnet,
                    "season": season,
                    "episode": episode,
                    "source_role": "season_pack_fallback",
                    "metadata": {
                        "origin": "notion",
                        "release_mode": "season_pack",
                        "season_pack": True,
                        "season": season,
                        "episode": episode,
                        "episode_notion_page_id": notion_page_id,
                        "release_title": release_title,
                    },
                }
            )
        return {
            "notion_page_id": notion_page_id,
            "notion_url": page.get("url"),
            "last_edited_time": page.get("last_edited_time"),
            "show_tmdb_id": _optional_int(_decode_notion_property(properties.get("Show TMDB ID"))),
            "show_title": str(_decode_notion_property(properties.get("Show Title")) or ""),
            "season": season,
            "episode": episode,
            "name": str(_decode_notion_property(properties.get("Episode Title")) or ""),
            "still_url": str(_decode_notion_property(properties.get("Still URL")) or ""),
            "runtime_minutes": _optional_int(_decode_notion_property(properties.get("Runtime"))),
            "watched": bool(_decode_notion_property(properties.get("Watched"))),
            "progress_percent": _optional_int(_decode_notion_property(properties.get("Progress Percent"))),
            "exact_magnet": exact_magnet,
            "fallback_magnet": fallback_magnet,
            "release_title": release_title,
            "release_mode": str(_decode_notion_property(properties.get("Release Mode")) or "").strip(),
            "playback_sources": items,
        }

    def _season_summaries(self, show: dict, episode_items: list[dict]) -> list[dict]:
        summary: dict[int, dict[str, Any]] = {}
        for item in episode_items:
            season = int(item.get("season") or 0)
            if season < 1:
                continue
            bucket = summary.setdefault(
                season,
                {
                    "season_number": season,
                    "name": f"Season {season}",
                    "episode_count": 0,
                    "poster_url": show.get("poster_url") or "",
                    "air_date": None,
                },
            )
            bucket["episode_count"] += 1
        return [summary[key] for key in sorted(summary)]

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        if not self.configured:
            raise MediaIntegrationError("Notion is not configured.")
        try:
            response = self.session.request(
                method,
                f"https://api.notion.com/v1{path}",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Notion-Version": self.VERSION,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=self.timeout_seconds,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise MediaIntegrationError("Notion is unavailable.") from exc
        if not response.ok:
            try:
                message = str(response.json().get("message") or "Notion request failed.")
            except ValueError:
                message = "Notion request failed."
            raise MediaIntegrationError(message)
        try:
            payload = response.json()
        except ValueError as exc:
            raise MediaIntegrationError("Notion returned an invalid response.") from exc
        if not isinstance(payload, dict):
            raise MediaIntegrationError("Notion returned an invalid response.")
        return payload


def _decode_notion_property(prop: dict | None) -> Any:
    if not prop:
        return None
    prop_type = prop.get("type")
    value = prop.get(prop_type)
    if prop_type in {"title", "rich_text"}:
        return "".join(str(item.get("plain_text") or "") for item in value or [])
    if prop_type in {"number", "checkbox", "url"}:
        return value
    if prop_type in {"select", "status"}:
        return value.get("name") if value else None
    if prop_type == "date":
        return value.get("start") if value else None
    if prop_type == "files":
        for item in value or []:
            file_type = item.get("type")
            file_value = item.get(file_type) or {}
            if file_value.get("url"):
                return file_value["url"]
    return None


def _encode_notion_property(prop_type: str | None, value: Any) -> dict | None:
    if prop_type in {"title", "rich_text"}:
        content = str(value or "")
        chunks = [content[index : index + 2000] for index in range(0, len(content), 2000)]
        if prop_type == "title":
            chunks = chunks[:1]
        return {
            prop_type: []
            if not chunks
            else [
                {"type": "text", "text": {"content": chunk}}
                for chunk in chunks[:50]
            ]
        }
    if prop_type == "number":
        return {"number": None if value in {None, ""} else float(value)}
    if prop_type == "checkbox":
        return {"checkbox": bool(value)}
    if prop_type in {"select", "status"}:
        return {prop_type: None if not value else {"name": str(value)}}
    if prop_type == "multi_select":
        return {"multi_select": [{"name": name} for name in _names(value)]}
    if prop_type == "date":
        return {"date": None if not value else {"start": str(value)}}
    if prop_type == "url":
        return {"url": str(value)[:2000] if value else None}
    return None


def _source_value(properties: dict, name: str, kind: str, label: str) -> dict | None:
    locator = str(_decode_notion_property(properties.get(name)) or "").strip()
    return {"kind": kind, "label": label, "locator": locator} if locator else None


def _notion_status(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    return {
        "i want to": "want_to_watch",
        "want to watch": "want_to_watch",
        "not finished": "watching",
        "watching": "watching",
        # Older rows may still use "Finished"; treat them as the single
        # current completed state while subsequent writes normalize to Watched.
        "finished": "watched",
        "watched": "watched",
    }.get(normalized, "unknown")


def _select_number(value: Any) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group()) if match else None


def _named_values(value: Any) -> list[dict[str, str]]:
    return [
        {"name": item.strip()}
        for item in re.split(r"[,;|]", str(value or ""))
        if item.strip()
    ]


def _names(value: Any) -> list[str]:
    if isinstance(value, list):
        values = [
            item.get("name") if isinstance(item, dict) else item
            for item in value
        ]
    else:
        values = re.split(r"[,;|]", str(value or ""))
    return _dedupe_strings(
        [str(item or "").strip() for item in values if str(item or "").strip()]
    )


def _names_text(value: Any) -> str:
    return ", ".join(_names(value))


def _normalize_title(value: Any) -> str:
    """Normalize titles only for matching; outbound queries retain TMDb text."""
    normalized = unicodedata.normalize("NFKC", str(value or "").casefold())
    normalized = normalized.translate(
        str.maketrans(
            {
                "ي": "ی",
                "ى": "ی",
                "ك": "ک",
                "ة": "ه",
                "ۀ": "ه",
                "أ": "ا",
                "إ": "ا",
                "ٱ": "ا",
                "ـ": "",
            }
        )
    )
    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^\w]+", " ", normalized).split())


def _release_profile(row: dict[str, Any]) -> dict[str, Any]:
    title = _normalize_title(row.get("title"))
    size = _integer(row.get("size"))
    score_adjustment = 0
    tags: list[str] = []

    if "2160p" in title or "4k" in title or "uhd" in title:
        quality_label = "4K"
        tags.append("4K")
        score_adjustment += 20
    elif "1080p" in title:
        quality_label = "1080p"
        tags.append("1080p")
        score_adjustment += 45
    elif "720p" in title:
        quality_label = "720p"
        tags.append("720p")
        score_adjustment += 18
    else:
        quality_label = "Quality unknown"

    if re.search(r"\b(?:cam|hdcam|telesync|ts|tc|hdts)\b", title):
        tags.append("Poor capture")
        score_adjustment -= 220
    if any(token in title for token in ("bluray", "blu ray", "bdrip", "brrip", "remux")):
        tags.append("BluRay")
        score_adjustment += 40
    elif any(token in title for token in ("web dl", "webdl", "webrip", "web rip")):
        tags.append("WEB")
        score_adjustment += 30

    if any(token in title for token in ("x265", "h265", "h 265", "hevc", "10bit", "10 bit")):
        codec_label = "HEVC"
        playback_label = "Transcode likely"
        tags.append("HEVC")
        score_adjustment -= 45
    elif any(token in title for token in ("x264", "h264", "h 264", "avc")):
        codec_label = "H.264"
        playback_label = "Browser friendly"
        tags.append("H.264")
        score_adjustment += 35
    else:
        codec_label = "Codec unknown"
        playback_label = "May need transcode"

    subtitle_tokens = ("multi subs", "multisubs", "subbed", "arabic", " ar ", "subs")
    if any(token in title for token in subtitle_tokens):
        subtitle_label = "Subtitle signal"
        tags.append("Subs")
        score_adjustment += 18
    elif any(
        token in title
        for token in ("bluray", "blu ray", "web dl", "webdl", "webrip", "remux")
    ):
        subtitle_label = "Good subtitle fit"
        score_adjustment += 12
    else:
        subtitle_label = "Subtitle fit unknown"

    if quality_label == "1080p" and 900 * 1024**2 <= size <= 8 * 1024**3:
        score_adjustment += 22
    if quality_label == "720p" and 500 * 1024**2 <= size <= 4 * 1024**3:
        score_adjustment += 12
    if quality_label == "4K" and size and size < 3 * 1024**3:
        score_adjustment -= 60

    return {
        "quality_label": quality_label,
        "codec_label": codec_label,
        "playback_label": playback_label,
        "subtitle_label": subtitle_label,
        "tags": _dedupe_strings(tags)[:5],
        "score_adjustment": score_adjustment,
    }


def _title_variants(item: dict[str, Any]) -> list[str]:
    return _dedupe_strings(
        [str(item.get("title") or "").strip(), str(item.get("original_title") or "").strip()]
    )


def _release_search_identity(details: dict[str, Any], alternative_titles: list[str]) -> dict[str, Any]:
    display_title = str(details.get("title") or "").strip()
    original_title = str(details.get("original_title") or "").strip()
    alternatives = _dedupe_strings(alternative_titles)
    native_aliases = _dedupe_strings(
        [
            *([original_title] if _contains_non_latin(original_title) else []),
            *[title for title in alternatives if _contains_non_latin(title)],
        ]
    )
    latin_alternatives = [title for title in alternatives if not _contains_non_latin(title)]
    original_is_native = _contains_non_latin(original_title)
    transliterated_aliases = _dedupe_strings(
        [
            title
            for title in latin_alternatives
            if _normalize_title(title) != _normalize_title(display_title)
        ]
        if original_is_native
        else []
    )
    international_aliases = _dedupe_strings(
        [display_title, *([] if original_is_native else [original_title])]
    )
    scheduled_normalizations = {
        _normalize_title(title)
        for title in [*native_aliases, *transliterated_aliases, *international_aliases]
    }
    alternative_aliases = _dedupe_strings(
        [
            title
            for title in alternatives
            if _normalize_title(title) not in scheduled_normalizations
        ]
    )
    title_variants = _dedupe_strings(
        [
            *native_aliases,
            *transliterated_aliases,
            *international_aliases,
            *alternative_aliases,
        ]
    )
    external_ids = dict(details.get("external_ids") or {})
    return {
        "tmdb_id": str(external_ids.get("tmdb_id") or details.get("tmdb_id") or ""),
        "imdb_id": str(external_ids.get("imdb_id") or ""),
        "year": details.get("year"),
        "display_title": display_title,
        "original_title": original_title,
        "original_language": str(details.get("original_language") or ""),
        "native_aliases": native_aliases,
        "transliterated_aliases": transliterated_aliases,
        "international_aliases": international_aliases,
        "alternative_aliases": alternative_aliases,
        "title_variants": title_variants,
    }


def _release_query_suffix(
    media_type: str, *, year: Any, season: int | None, episode: int | None
) -> str:
    if media_type == "tv" and season and episode:
        return f" S{season:02d}E{episode:02d}"
    if media_type == "tv" and season:
        return f" S{season:02d}"
    return f" {_optional_int(year)}" if _optional_int(year) else ""


def _contains_non_latin(value: str) -> bool:
    return any("LATIN" not in unicodedata.name(character, "") for character in value if character.isalpha())


def _release_title_match_score(title: str, match_context: dict[str, Any]) -> tuple[float, int]:
    tiers = (
        ("original_title", [match_context.get("original_title")], 60),
        ("native_aliases", match_context.get("native_aliases") or [], 60),
        ("alternative_aliases", match_context.get("alternative_aliases") or [], 55),
        ("transliterated_aliases", match_context.get("transliterated_aliases") or [], 40),
        ("international_aliases", match_context.get("international_aliases") or [], 45),
        ("title_variants", match_context.get("title_variants") or [], 35),
    )
    best_score = 0.0
    strength = 0
    for _tier, variants, exact_score in tiers:
        for variant in variants:
            normalized_variant = _normalize_title(variant)
            if not normalized_variant:
                continue
            if title.startswith(normalized_variant):
                best_score = max(best_score, float(exact_score))
                strength = max(strength, 2)
            elif normalized_variant in title:
                index = title.find(normalized_variant)
                best_score = max(best_score, float(exact_score if index <= 14 else exact_score / 3))
                if index <= 14:
                    strength = max(strength, 1)
    return best_score, strength


def _external_identifier(row: dict, *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _release_result_identity(row: dict) -> tuple[str, str, int]:
    return (
        _normalize_title(row.get("title")),
        _normalize_title(row.get("tracker")),
        _integer(row.get("size")),
    )


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for value in values:
        cleaned = " ".join(str(value or "").split())
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        results.append(cleaned)
    return results


def _magnet_info_hash(magnet: str) -> str:
    match = re.search(r"(?:\?|&)xt=urn:btih:([^&]+)", magnet, flags=re.IGNORECASE)
    return match.group(1).casefold() if match else ""


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int:
    return _optional_int(value) or 0
