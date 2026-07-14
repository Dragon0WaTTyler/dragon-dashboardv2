from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PLAYLIST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,100}$")


class YouTubeProviderError(ValueError):
    """A safe provider failure that never includes credentials or request URLs."""


class YouTubePlaylistClient:
    endpoint = "https://www.googleapis.com/youtube/v3/playlistItems"

    def __init__(
        self,
        api_key: str,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout: int = 20,
    ) -> None:
        if not api_key.strip():
            raise YouTubeProviderError("YouTube API key is not configured.")
        self._api_key = api_key.strip()
        self._opener = opener
        self._timeout = timeout

    def fetch_playlist(self, playlist_id: str, *, maximum: int = 5000) -> list[dict[str, Any]]:
        playlist_id = playlist_id.strip()
        if not PLAYLIST_ID_PATTERN.fullmatch(playlist_id):
            raise YouTubeProviderError("The configured YouTube playlist ID is invalid.")
        maximum = max(1, min(maximum, 5000))

        items: list[dict[str, Any]] = []
        page_token = ""
        while len(items) < maximum:
            parameters = {
                "part": "snippet",
                "playlistId": playlist_id,
                "maxResults": min(50, maximum - len(items)),
                "key": self._api_key,
            }
            if page_token:
                parameters["pageToken"] = page_token
            request = Request(  # noqa: S310 - the endpoint is a fixed HTTPS URL.
                f"{self.endpoint}?{urlencode(parameters)}",
                headers={"Accept": "application/json", "User-Agent": "DragonV2/1.0"},
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    payload = json.load(response)
            except HTTPError as exc:
                raise YouTubeProviderError(
                    f"YouTube playlist request failed with HTTP {exc.code}."
                ) from None
            except (URLError, TimeoutError, json.JSONDecodeError, UnicodeError):
                raise YouTubeProviderError(
                    "YouTube playlist request could not be completed."
                ) from None

            page_items = payload.get("items", [])
            if not isinstance(page_items, list):
                raise YouTubeProviderError("YouTube returned an invalid playlist response.")
            items.extend(item for item in page_items if isinstance(item, dict))
            page_token = str(payload.get("nextPageToken") or "")
            if not page_token:
                break
        return items[:maximum]
