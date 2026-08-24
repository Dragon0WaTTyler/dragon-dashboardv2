from __future__ import annotations

import json
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PLAYLIST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,100}$")
CHANNEL_ID_PATTERN = re.compile(r"^UC[A-Za-z0-9_-]{10,100}$")
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
PLAYLIST_ITEM_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
DURATION_PATTERN = re.compile(
    r"^P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)


def duration_seconds(value: object) -> int:
    """Convert a YouTube ISO-8601 duration to whole seconds."""
    match = DURATION_PATTERN.fullmatch(str(value or "").strip().upper())
    if match is None:
        return 0
    parts = {name: int(number or 0) for name, number in match.groupdict().items()}
    return (
        parts["days"] * 86_400
        + parts["hours"] * 3_600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


class YouTubeProviderError(ValueError):
    """A safe provider failure that never includes credentials or request URLs."""


def _request_error_message(error: HTTPError) -> str:
    """Turn selected Google API errors into safe, actionable messages."""
    if error.code == 403:
        try:
            payload = json.loads(error.read().decode("utf-8", "replace"))
            details = payload.get("error", {}).get("errors", [])
            reasons = {
                str(detail.get("reason") or "")
                for detail in details
                if isinstance(detail, dict)
            }
        except (AttributeError, UnicodeError, json.JSONDecodeError):
            reasons = set()
        if "quotaExceeded" in reasons or "dailyLimitExceeded" in reasons:
            return (
                "YouTube API quota has been exceeded. It resets daily; try again after "
                "the quota resets or increase the quota for this Google Cloud project."
            )
    return f"YouTube playlist request failed with HTTP {error.code}."


class YouTubePlaylistClient:
    endpoint = "https://www.googleapis.com/youtube/v3/playlistItems"
    videos_endpoint = "https://www.googleapis.com/youtube/v3/videos"
    authorization_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"

    def __init__(
        self,
        api_key: str = "",
        *,
        oauth_token_path: str | Path | None = None,
        opener: Callable[..., Any] = urlopen,
        timeout: int = 20,
    ) -> None:
        self._api_key = api_key.strip()
        self._oauth_token_path = Path(oauth_token_path) if oauth_token_path else None
        if not self._api_key and self._oauth_token_path is None:
            raise YouTubeProviderError("YouTube API credentials are not configured.")
        self._opener = opener
        self._timeout = timeout

    def _oauth_payload(self, *, refresh_if_expired: bool = True) -> dict[str, Any] | None:
        if self._oauth_token_path is None or not self._oauth_token_path.is_file():
            return None
        try:
            payload = json.loads(self._oauth_token_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise YouTubeProviderError("YouTube OAuth credentials could not be read.") from exc
        if not isinstance(payload, dict) or not str(payload.get("token") or "").strip():
            raise YouTubeProviderError("YouTube OAuth credentials are incomplete.")
        if refresh_if_expired and self._oauth_expired(payload):
            return self._refresh_oauth_token(payload)
        return payload

    @staticmethod
    def _oauth_expired(payload: dict[str, Any]) -> bool:
        raw_expiry = str(payload.get("expiry") or "").strip()
        if not raw_expiry:
            return False
        parsed: datetime | None = None
        try:
            parsed = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.strptime(raw_expiry, "%m/%d/%Y %H:%M:%S")
            except ValueError:
                return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed <= datetime.now(timezone.utc) + timedelta(seconds=30)

    def _refresh_oauth_token(self, payload: dict[str, Any]) -> dict[str, Any]:
        token_uri = str(payload.get("token_uri") or "").strip()
        refresh_token = str(payload.get("refresh_token") or "").strip()
        client_id = str(payload.get("client_id") or "").strip()
        client_secret = str(payload.get("client_secret") or "").strip()
        if not token_uri.startswith("https://") or not refresh_token or not client_id:
            raise YouTubeProviderError("YouTube OAuth credentials cannot be refreshed.")
        form = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        request = Request(  # noqa: S310 - token URI is stored in the private OAuth credential.
            token_uri,
            data=urlencode(form).encode(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                refreshed = json.load(response)
        except HTTPError as exc:
            if exc.code == 400:
                raise YouTubeProviderError(
                    "YouTube authorization has expired or been revoked. "
                    "Reconnect YouTube, then try again."
                ) from None
            raise YouTubeProviderError(
                f"YouTube OAuth refresh failed with HTTP {exc.code}."
            ) from None
        except (URLError, TimeoutError, json.JSONDecodeError, UnicodeError):
            raise YouTubeProviderError("YouTube OAuth refresh could not be completed.") from None
        access_token = str(refreshed.get("access_token") or "").strip()
        if not access_token:
            raise YouTubeProviderError("YouTube OAuth refresh returned no access token.")
        payload["token"] = access_token
        payload["expiry"] = (
            datetime.now(timezone.utc) + timedelta(seconds=max(1, int(refreshed.get("expires_in") or 3600)))
        ).isoformat()
        self._write_oauth_payload(payload)
        return payload

    def _write_oauth_payload(self, payload: dict[str, Any]) -> None:
        if self._oauth_token_path is None:
            raise YouTubeProviderError("YouTube OAuth credentials are not configured.")
        try:
            self._oauth_token_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            raise YouTubeProviderError(
                "YouTube OAuth credentials could not be updated."
            ) from exc

    def authorization_url(self, redirect_uri: str, state: str) -> str:
        payload = self._oauth_payload(refresh_if_expired=False)
        if payload is None:
            raise YouTubeProviderError("YouTube OAuth credentials are not configured.")
        client_id = str(payload.get("client_id") or "").strip()
        if not client_id or not redirect_uri.startswith(("http://", "https://")) or not state:
            raise YouTubeProviderError("YouTube OAuth connection could not be started.")
        scopes = payload.get("scopes")
        scope = " ".join(str(item).strip() for item in scopes) if isinstance(scopes, list) else ""
        parameters = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope or "https://www.googleapis.com/auth/youtube.force-ssl",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{self.authorization_endpoint}?{urlencode(parameters)}"

    def exchange_authorization_code(self, code: str, redirect_uri: str) -> None:
        payload = self._oauth_payload(refresh_if_expired=False)
        if payload is None:
            raise YouTubeProviderError("YouTube OAuth credentials are not configured.")
        code = code.strip()
        token_uri = str(payload.get("token_uri") or "").strip()
        client_id = str(payload.get("client_id") or "").strip()
        client_secret = str(payload.get("client_secret") or "").strip()
        if not code or not token_uri.startswith("https://") or not client_id:
            raise YouTubeProviderError("YouTube authorization response is invalid.")
        request = Request(  # noqa: S310 - token URI is stored in the private OAuth credential.
            token_uri,
            data=urlencode(
                {
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                }
            ).encode(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                exchanged = json.load(response)
        except HTTPError as exc:
            raise YouTubeProviderError(
                f"YouTube authorization exchange failed with HTTP {exc.code}."
            ) from None
        except (URLError, TimeoutError, json.JSONDecodeError, UnicodeError):
            raise YouTubeProviderError(
                "YouTube authorization exchange could not be completed."
            ) from None
        access_token = str(exchanged.get("access_token") or "").strip()
        if not access_token:
            raise YouTubeProviderError("YouTube authorization exchange returned no access token.")
        payload["token"] = access_token
        if str(exchanged.get("refresh_token") or "").strip():
            payload["refresh_token"] = str(exchanged["refresh_token"]).strip()
        payload["expiry"] = (
            datetime.now(timezone.utc) + timedelta(seconds=max(1, int(exchanged.get("expires_in") or 3600)))
        ).isoformat()
        self._write_oauth_payload(payload)

    def _request(
        self,
        endpoint: str,
        parameters: dict[str, Any],
        *,
        method: str = "GET",
        json_response: bool = True,
    ) -> dict[str, Any] | None:
        oauth = self._oauth_payload()
        if oauth is None and not self._api_key:
            raise YouTubeProviderError("YouTube API credentials are not configured.")
        for attempt in range(2):
            query = dict(parameters)
            headers = {"Accept": "application/json", "User-Agent": "DragonV2/1.0"}
            if oauth is not None:
                headers["Authorization"] = f"Bearer {oauth['token']}"
            else:
                query["key"] = self._api_key
            request = Request(  # noqa: S310 - endpoint is a fixed YouTube HTTPS API URL.
                f"{endpoint}?{urlencode(query)}", headers=headers, method=method
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    return json.load(response) if json_response else None
            except HTTPError as exc:
                if exc.code == 401 and oauth is not None and attempt == 0:
                    oauth = self._refresh_oauth_token(oauth)
                    continue
                raise YouTubeProviderError(_request_error_message(exc)) from None
            except (URLError, TimeoutError, json.JSONDecodeError, UnicodeError):
                raise YouTubeProviderError(
                    "YouTube playlist request could not be completed."
                ) from None
        raise YouTubeProviderError("YouTube playlist request could not be completed.")

    def fetch_playlist(self, playlist_id: str, *, maximum: int = 5000) -> list[dict[str, Any]]:
        playlist_id = playlist_id.strip()
        if not PLAYLIST_ID_PATTERN.fullmatch(playlist_id):
            raise YouTubeProviderError("The configured YouTube playlist ID is invalid.")
        maximum = max(1, min(maximum, 10000))

        items: list[dict[str, Any]] = []
        page_token = ""
        while len(items) < maximum:
            parameters = {
                "part": "snippet",
                "playlistId": playlist_id,
                "maxResults": min(50, maximum - len(items)),
            }
            if page_token:
                parameters["pageToken"] = page_token
            payload = self._request(self.endpoint, parameters) or {}

            page_items = payload.get("items", [])
            if not isinstance(page_items, list):
                raise YouTubeProviderError("YouTube returned an invalid playlist response.")
            items.extend(item for item in page_items if isinstance(item, dict))
            page_token = str(payload.get("nextPageToken") or "")
            if not page_token:
                break
        return items[:maximum]

    def fetch_durations(
        self, video_ids: list[str] | set[str] | tuple[str, ...], *, maximum: int = 5000
    ) -> dict[str, int]:
        """Fetch durations in API-sized batches without exposing the API key."""
        maximum = max(1, min(maximum, 10000))
        clean_ids = list(
            dict.fromkeys(
                video_id.strip()
                for video_id in video_ids
                if VIDEO_ID_PATTERN.fullmatch(str(video_id).strip())
            )
        )[:maximum]
        durations: dict[str, int] = {}

        for start in range(0, len(clean_ids), 50):
            batch = clean_ids[start : start + 50]
            parameters = {
                "part": "contentDetails",
                "id": ",".join(batch),
                "maxResults": len(batch),
            }
            payload = self._request(self.videos_endpoint, parameters) or {}

            page_items = payload.get("items", [])
            if not isinstance(page_items, list):
                raise YouTubeProviderError("YouTube returned an invalid duration response.")
            for item in page_items:
                if not isinstance(item, dict):
                    continue
                video_id = str(item.get("id") or "").strip()
                details = item.get("contentDetails") or {}
                seconds = duration_seconds(
                    details.get("duration") if isinstance(details, dict) else ""
                )
                if video_id in batch and seconds > 0:
                    durations[video_id] = seconds
        return durations

    def fetch_latest_channel_uploads(
        self,
        channel_ids: list[str] | set[str] | tuple[str, ...],
        *,
        maximum: int = 5000,
    ) -> dict[str, dict[str, Any]]:
        maximum = max(1, min(maximum, 10000))
        clean_ids = list(
            dict.fromkeys(
                channel_id.strip()
                for channel_id in channel_ids
                if CHANNEL_ID_PATTERN.fullmatch(str(channel_id).strip())
            )
        )[:maximum]
        latest: dict[str, dict[str, Any]] = {}

        for channel_id in clean_ids:
            upload_playlist_id = f"UU{channel_id[2:]}"
            try:
                items = self.fetch_playlist(upload_playlist_id, maximum=1)
            except YouTubeProviderError:
                continue
            if items:
                latest[channel_id] = items[0]
        return latest

    def fetch_channel_uploads(
        self,
        channel_limits: dict[str, int],
        *,
        maximum: int = 5000,
    ) -> dict[str, list[dict[str, Any]]]:
        maximum = max(1, min(maximum, 5000))
        fetched = 0
        bounded_limits: dict[str, int] = {}
        clean_limits = {
            channel_id.strip(): max(1, min(int(limit or 1), 200))
            for channel_id, limit in channel_limits.items()
            if CHANNEL_ID_PATTERN.fullmatch(str(channel_id).strip())
        }

        for channel_id, limit in clean_limits.items():
            if fetched >= maximum:
                break
            request_limit = min(limit, maximum - fetched)
            bounded_limits[channel_id] = request_limit
            fetched += request_limit

        def fetch_one(channel_id: str, limit: int) -> tuple[str, list[dict[str, Any]]]:
            upload_playlist_id = f"UU{channel_id[2:]}"
            try:
                return channel_id, self.fetch_playlist(upload_playlist_id, maximum=limit)
            except YouTubeProviderError:
                return channel_id, []

        uploads: dict[str, list[dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = [
                executor.submit(fetch_one, channel_id, limit)
                for channel_id, limit in bounded_limits.items()
            ]
            for future in as_completed(futures):
                channel_id, items = future.result()
                if items:
                    uploads[channel_id] = items
        return uploads

    def delete_playlist_item(self, playlist_item_id: str) -> None:
        playlist_item_id = playlist_item_id.strip()
        if not PLAYLIST_ITEM_ID_PATTERN.fullmatch(playlist_item_id):
            raise YouTubeProviderError("The YouTube playlist item ID is invalid.")
        if self._oauth_payload() is None:
            raise YouTubeProviderError(
                "Removing a video from YouTube requires a connected OAuth account."
            )
        self._request(
            self.endpoint,
            {"id": playlist_item_id},
            method="DELETE",
            json_response=False,
        )
