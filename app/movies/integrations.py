from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import requests


class MediaIntegrationError(RuntimeError):
    """A credential-safe failure from an external movie integration."""


class TmdbCatalogProvider:
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

    @property
    def configured(self) -> bool:
        return bool(self.api_key or self.read_access_token)

    def search(self, query: str, media_type: str = "all", *, limit: int = 20) -> list[dict]:
        payload = self._request(
            "/search/multi",
            {"query": query, "include_adult": "false", "language": "en-US", "page": 1},
        )
        ranked: list[tuple[float, dict]] = []
        normalized_query = _normalize_title(query)
        for item in payload.get("results") or []:
            item_type = str(item.get("media_type") or "")
            if item_type not in {"movie", "tv"}:
                continue
            if media_type in {"movie", "tv"} and item_type != media_type:
                continue
            summary = self._summary(item, item_type)
            ranked.append((self._search_score(summary, normalized_query, item), summary))
        ranked.sort(
            key=lambda pair: (
                -pair[0],
                pair[1]["title"].casefold(),
                -(pair[1].get("year") or 0),
            )
        )
        return [
            summary
            for _, summary in ranked[: max(1, min(limit, 40))]
        ]

    def details(self, media_type: str, tmdb_id: int) -> dict:
        if media_type not in {"movie", "tv"}:
            raise MediaIntegrationError("Media type must be movie or series.")
        payload = self._request(
            f"/{media_type}/{int(tmdb_id)}",
            {"language": "en-US", "append_to_response": "credits,external_ids"},
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
                    {"name": str(member.get("name"))}
                    for member in (credits.get("cast") or [])[:12]
                    if member.get("name")
                ],
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
                if int(season.get("season_number") or 0) > 0
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

    def _search_score(self, summary: dict, normalized_query: str, payload: dict) -> float:
        title = _normalize_title(summary.get("title"))
        original_title = _normalize_title(summary.get("original_title"))
        query_tokens = set(normalized_query.split())
        title_tokens = set(title.split())
        shared = len(query_tokens & title_tokens)
        score = shared * 24
        if title == normalized_query:
            score += 420
        elif original_title and original_title == normalized_query:
            score += 320
        elif title.startswith(normalized_query):
            score += 180
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


class JackettReleaseProvider:
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
            return self._filter(rows, limit, match_context=match_context)
        except (requests.RequestException, ValueError) as exc:
            raise MediaIntegrationError("Jackett is unavailable.") from exc

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
                }
            )
        return results

    def _filter(
        self,
        rows: list[dict],
        limit: int,
        *,
        match_context: dict[str, Any] | None = None,
    ) -> list[dict]:
        unique: dict[str, dict] = {}
        for row in rows:
            magnet = str(row.get("magnet_uri") or "")
            if not magnet.startswith("magnet:?") or row.get("seeders", 0) < self.min_seeders:
                continue
            info_hash = _magnet_info_hash(magnet)
            key = info_hash or magnet.split("&", 1)[0].casefold()
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
        if exact:
            ranked = exact + season_pack + general
        elif season_pack:
            ranked = season_pack + general
        else:
            ranked = [item for item in ranked if item[0] > -250]
        results = []
        for score, match_kind, row in ranked[: max(1, min(int(limit), 100))]:
            results.append(
                {
                    **row,
                    "match_kind": match_kind,
                    "match_score": int(score),
                }
            )
        return results

    def _release_score(
        self, row: dict, match_context: dict[str, Any]
    ) -> tuple[float, str]:
        title = _normalize_title(row.get("title"))
        score = float(row.get("seeders") or 0) * 12
        match_kind = "general"
        for variant in match_context.get("title_variants") or []:
            normalized_variant = _normalize_title(variant)
            if not normalized_variant:
                continue
            if title.startswith(normalized_variant):
                score += 80
            elif normalized_variant in title:
                score += 40
        if match_context.get("year") and str(match_context["year"]) in title:
            score += 60
        season = _optional_int(match_context.get("season"))
        episode = _optional_int(match_context.get("episode"))
        episode_code = str(match_context.get("episode_code") or "").casefold()
        alt_episode_code = str(match_context.get("alt_episode_code") or "").casefold()
        episode_title = _normalize_title(match_context.get("episode_title"))
        if episode and season:
            if episode_code and episode_code.casefold() in title:
                return score + 700, "exact_episode"
            if alt_episode_code and alt_episode_code.casefold() in title:
                return score + 660, "exact_episode"
            if episode_title and episode_title in title:
                score += 220
            season_tokens = (
                f"s{season:02d}",
                f"season {season}",
                f"{season}x",
            )
            if any(token in title for token in season_tokens):
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
        return score, match_kind


class NotionMovieProvider:
    VERSION = "2025-09-03"
    REQUIRED_PROPERTIES = {
        "TMDB ID": {"number": {}},
        "Media Type": {"select": {}},
        "Season": {"number": {}},
        "Episode": {"number": {}},
        "Release Title": {"rich_text": {}},
        "Magnet Link Used": {"rich_text": {}},
        "Watched": {"checkbox": {}},
        "Date Watched": {"date": {}},
    }

    def __init__(
        self,
        *,
        token: str,
        database_id: str = "",
        data_source_id: str = "",
        session: requests.Session | None = None,
        timeout_seconds: float = 20,
    ) -> None:
        self.token = token.strip()
        self.database_id = database_id.strip().replace("-", "")
        self._data_source_id = data_source_id.strip().replace("-", "")
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self._schema: dict[str, dict] | None = None

    @property
    def configured(self) -> bool:
        return bool(self.token and (self.database_id or self._data_source_id))

    @property
    def data_source_id(self) -> str:
        if self._data_source_id:
            return self._data_source_id
        payload = self._request("GET", f"/databases/{self.database_id}")
        sources = payload.get("data_sources") or []
        if not sources:
            raise MediaIntegrationError("The Notion database has no accessible data source.")
        self._data_source_id = str(sources[0]["id"])
        return self._data_source_id

    def schema(self, *, refresh: bool = False) -> dict[str, dict]:
        if self._schema is None or refresh:
            payload = self._request("GET", f"/data_sources/{self.data_source_id}")
            self._schema = dict(payload.get("properties") or {})
        return self._schema

    def ensure_writeback_schema(self) -> None:
        schema = self.schema()
        missing = {
            name: definition
            for name, definition in self.REQUIRED_PROPERTIES.items()
            if name not in schema
        }
        if not missing:
            return
        self._request(
            "PATCH",
            f"/data_sources/{self.data_source_id}",
            json={"properties": missing},
        )
        self.schema(refresh=True)

    def list_items(self) -> list[dict]:
        if not self.configured:
            raise MediaIntegrationError("Notion is not configured.")
        pages = []
        cursor = None
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            payload = self._request(
                "POST", f"/data_sources/{self.data_source_id}/query", json=body
            )
            pages.extend(payload.get("results") or [])
            cursor = payload.get("next_cursor")
            if not payload.get("has_more") or not cursor:
                break
        return [self._page_item(page) for page in pages if not page.get("in_trash")]

    def upsert_media(
        self,
        media: dict,
        *,
        magnet_uri: str = "",
        release_title: str = "",
        season: int | None = None,
        episode: int | None = None,
        status: str = "watching",
    ) -> dict:
        self.ensure_writeback_schema()
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
        return self._page_item(payload)

    def mark_watched(self, notion_page_id: str, *, started: bool = False) -> None:
        self.ensure_writeback_schema()
        now = datetime.now(UTC).isoformat()
        values = (
            {"watching history": now, "Status": "Not finished"}
            if started
            else {
                "Watched": True,
                "Date Watched": now,
                "finishing history": now,
                "Status": "Finished",
            }
        )
        properties = self._properties(values)
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
            "finished": "Finished",
            "watched": "Watched",
        }.get(status, "Not finished")
        values = {
            "Name": media.get("title"),
            "TMDB ID": media.get("tmdb_id"),
            "Media Type": "Movie" if media_type == "movie" else "Series",
            "Year": media.get("year"),
            "Overview": media.get("overview"),
            "Poster URL": media.get("poster_url"),
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
        return self._properties(values)

    def _properties(self, values: dict[str, Any]) -> dict:
        schema = self.schema()
        properties = {}
        for name, value in values.items():
            definition = schema.get(name)
            if not definition:
                continue
            encoded = _encode_notion_property(definition.get("type"), value)
            if encoded is not None:
                properties[name] = encoded
        return properties

    def _page_item(self, page: dict) -> dict:
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
        score = _select_number(_decode_notion_property(properties.get("Score /5")))
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
            "personal_score": score,
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
        return {"number": None if value in {None, ""} else int(value)}
    if prop_type == "checkbox":
        return {"checkbox": bool(value)}
    if prop_type in {"select", "status"}:
        return {prop_type: None if not value else {"name": str(value)}}
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
        "finished": "finished",
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


def _normalize_title(value: Any) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(value or "").casefold()).split())


def _title_variants(item: dict[str, Any]) -> list[str]:
    return _dedupe_strings(
        [str(item.get("title") or "").strip(), str(item.get("original_title") or "").strip()]
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
