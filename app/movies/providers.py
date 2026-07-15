from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

import requests

IMDB_ID_PATTERN = re.compile(r"^tt\d{5,12}$")
TMDB_API_BASE_URL = "https://api.themoviedb.org/3"


class TmdbIdentityError(ValueError):
    """A safe TMDB lookup failure that never exposes credentials or request URLs."""


def _normalized_title(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())


def _result_title(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("name") or "").strip()


def _result_year(item: dict[str, Any]) -> int | None:
    raw_date = str(item.get("release_date") or item.get("first_air_date") or "")
    return int(raw_date[:4]) if raw_date[:4].isdigit() else None


class TmdbIdentityProvider:
    def __init__(
        self,
        *,
        api_key: str = "",
        read_access_token: str = "",
        session: requests.Session | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        self.api_key = api_key.strip()
        self.read_access_token = read_access_token.strip()
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self.cache: dict[str, dict[str, str]] = {}

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict:
        if not self.api_key and not self.read_access_token:
            raise TmdbIdentityError("TMDB credentials are not configured.")
        request_params = dict(params or {})
        headers = {"Accept": "application/json"}
        if self.read_access_token:
            headers["Authorization"] = f"Bearer {self.read_access_token}"
        else:
            request_params["api_key"] = self.api_key
        try:
            response = self.session.get(
                f"{TMDB_API_BASE_URL}{path}",
                params=request_params,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TmdbIdentityError("TMDB identity lookup is unavailable.") from exc
        if not isinstance(payload, dict):
            raise TmdbIdentityError("TMDB returned an invalid identity response.")
        return payload

    def _external_ids(self, media_type: str, tmdb_id: str) -> dict[str, str]:
        payload = self._request(f"/{media_type}/{tmdb_id}/external_ids")
        imdb_id = str(payload.get("imdb_id") or "").strip().lower()
        if not IMDB_ID_PATTERN.fullmatch(imdb_id):
            raise TmdbIdentityError("TMDB did not return an IMDb ID for this title.")
        return {"tmdb_id": tmdb_id, "tmdb_type": media_type, "imdb_id": imdb_id}

    def resolve(
        self,
        *,
        title: str,
        year: int | None,
        media_type: str,
        external_ids: dict | None = None,
    ) -> dict[str, str]:
        known_ids = dict(external_ids or {})
        known_imdb = str(known_ids.get("imdb_id") or known_ids.get("imdb") or "").lower()
        if IMDB_ID_PATTERN.fullmatch(known_imdb):
            return {
                "imdb_id": known_imdb,
                **{
                    key: str(known_ids[key])
                    for key in ("tmdb_id", "tmdb_type")
                    if known_ids.get(key)
                },
            }

        known_tmdb = str(known_ids.get("tmdb_id") or "").strip()
        known_type = str(known_ids.get("tmdb_type") or "").strip().lower()
        if known_tmdb.isdigit() and known_type in {"movie", "tv"}:
            return self._external_ids(known_type, known_tmdb)

        normalized = _normalized_title(title)
        if not normalized:
            raise TmdbIdentityError("A movie title is required for TMDB lookup.")
        cache_key = f"{normalized}|{year or ''}|{media_type}"
        if cache_key in self.cache:
            return dict(self.cache[cache_key])

        preferred_type = "tv" if media_type.lower() in {"tv", "series", "show"} else "movie"
        candidates: list[tuple[float, str, dict[str, Any]]] = []
        for candidate_type in (preferred_type, "tv" if preferred_type == "movie" else "movie"):
            params: dict[str, Any] = {
                "query": title,
                "include_adult": "false",
                "language": "en-US",
                "page": 1,
            }
            if year:
                params["year" if candidate_type == "movie" else "first_air_date_year"] = year
            payload = self._request(f"/search/{candidate_type}", params)
            results = payload.get("results") or []
            if not isinstance(results, list):
                raise TmdbIdentityError("TMDB returned an invalid search response.")
            for item in results:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                candidate_title = _normalized_title(_result_title(item))
                similarity = SequenceMatcher(None, normalized, candidate_title).ratio()
                if similarity < 0.72:
                    continue
                candidate_year = _result_year(item)
                year_score = 0
                if year and candidate_year:
                    difference = abs(year - candidate_year)
                    if difference == 0:
                        year_score = 30
                    elif difference == 1:
                        year_score = 15
                    else:
                        year_score = -difference * 4
                type_score = 5 if candidate_type == preferred_type else 0
                score = similarity * 100 + year_score + type_score
                candidates.append((score, candidate_type, item))

        if not candidates:
            raise TmdbIdentityError("TMDB could not match this title.")
        _, resolved_type, resolved_item = max(candidates, key=lambda candidate: candidate[0])
        result = self._external_ids(resolved_type, str(resolved_item["id"]))
        self.cache[cache_key] = dict(result)
        return result
