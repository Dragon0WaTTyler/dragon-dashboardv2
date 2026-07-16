from __future__ import annotations

from datetime import date

import requests


class TmdbError(RuntimeError):
    pass


class TmdbClient:
    def __init__(self, config: dict):
        self.api_key = config.get("TMDB_API_KEY", "")
        self.api_token = config.get("TMDB_API_TOKEN", "")
        self.base_url = config["TMDB_BASE_URL"].rstrip("/")
        self.image_base_url = config["TMDB_IMAGE_BASE_URL"].rstrip("/")
        self.timeout = config["MEDIA_HTTP_TIMEOUT"]
        self.search_limit = max(1, min(40, config["MEDIA_SEARCH_LIMIT"]))
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        if self.api_token:
            self.session.headers["Authorization"] = f"Bearer {self.api_token}"

    @property
    def configured(self) -> bool:
        return bool(self.api_token or self.api_key)

    def search(self, query: str, media_type: str = "all") -> list[dict]:
        payload = self._get("/search/multi", {"query": query, "include_adult": "false"})
        results = []
        for item in payload.get("results", []):
            item_type = item.get("media_type")
            if item_type not in {"movie", "tv"}:
                continue
            if media_type in {"movie", "tv"} and item_type != media_type:
                continue
            results.append(self._summary(item, item_type))
            if len(results) >= self.search_limit:
                break
        return results

    def details(self, media_type: str, tmdb_id: int) -> dict:
        if media_type not in {"movie", "tv"}:
            raise TmdbError("media_type must be movie or tv")
        item = self._get(f"/{media_type}/{int(tmdb_id)}")
        summary = self._summary(item, media_type)
        summary["genres"] = [genre.get("name") for genre in item.get("genres", []) if genre.get("name")]
        if media_type == "tv":
            summary["number_of_seasons"] = item.get("number_of_seasons") or 0
            summary["number_of_episodes"] = item.get("number_of_episodes") or 0
            summary["seasons"] = [self._season_summary(season) for season in item.get("seasons", [])]
        return summary

    def seasons(self, tmdb_id: int) -> list[dict]:
        details = self.details("tv", tmdb_id)
        return [season for season in details.get("seasons", []) if season["season_number"] >= 0]

    def episodes(self, tmdb_id: int, season_number: int) -> list[dict]:
        payload = self._get(f"/tv/{int(tmdb_id)}/season/{int(season_number)}")
        return [
            {
                "id": episode.get("id"),
                "name": episode.get("name") or f"Episode {episode.get('episode_number', '')}",
                "overview": episode.get("overview") or "",
                "episode_number": episode.get("episode_number"),
                "season_number": episode.get("season_number", season_number),
                "air_date": episode.get("air_date"),
                "still_url": self._image_url(episode.get("still_path")),
                "runtime": episode.get("runtime"),
            }
            for episode in payload.get("episodes", [])
        ]

    def release_query(
        self,
        media_type: str,
        tmdb_id: int,
        season: int | None = None,
        episode: int | None = None,
    ) -> tuple[dict, str]:
        details = self.details(media_type, tmdb_id)
        if media_type == "movie":
            query = " ".join(part for part in (details["title"], str(details.get("year") or "")) if part)
        elif episode is not None:
            query = f"{details['title']} S{int(season or 0):02d}E{int(episode):02d}"
        elif season is not None:
            query = f"{details['title']} S{int(season):02d}"
        else:
            query = details["title"]
        return details, query

    def _get(self, path: str, params: dict | None = None) -> dict:
        if not self.configured:
            raise TmdbError("TMDB is not configured")
        params = dict(params or {})
        if self.api_key and not self.api_token:
            params["api_key"] = self.api_key
        try:
            response = self.session.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        except requests.RequestException as error:
            raise TmdbError(f"TMDB request failed: {error}") from error
        if response.status_code >= 400:
            try:
                message = response.json().get("status_message")
            except ValueError:
                message = None
            raise TmdbError(message or f"TMDB returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as error:
            raise TmdbError("TMDB returned invalid JSON") from error

    def _summary(self, item: dict, media_type: str) -> dict:
        released = item.get("release_date") if media_type == "movie" else item.get("first_air_date")
        year = None
        if released:
            try:
                year = int(str(released)[:4])
            except ValueError:
                pass
        return {
            "tmdb_id": int(item["id"]),
            "media_type": media_type,
            "type_label": "Movie" if media_type == "movie" else "Series",
            "title": item.get("title") or item.get("name") or "Untitled",
            "original_title": item.get("original_title") or item.get("original_name") or "",
            "overview": item.get("overview") or "",
            "year": year,
            "release_date": released,
            "poster_url": self._image_url(item.get("poster_path")),
            "backdrop_url": self._image_url(item.get("backdrop_path")),
            "rating": item.get("vote_average"),
        }

    def _season_summary(self, season: dict) -> dict:
        return {
            "id": season.get("id"),
            "name": season.get("name") or f"Season {season.get('season_number', '')}",
            "season_number": int(season.get("season_number") or 0),
            "episode_count": int(season.get("episode_count") or 0),
            "air_date": season.get("air_date"),
            "poster_url": self._image_url(season.get("poster_path")),
        }

    def _image_url(self, path: str | None) -> str | None:
        return f"{self.image_base_url}{path}" if path else None
