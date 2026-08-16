"""Manual, account-scoped host-library sync providers.

The sync code only inventories files reachable through the configured account
API.  It never searches a host's global catalogue and never runs while a
movie-detail page is loading.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from app.extensions import db
from app.playback.catalog import CatalogImportService
from app.playback.models import ImportBatch, ProviderAccountAsset
from app.playback.providers import indexed_embed_provider_spec
from app.shared.time import utc_now

STREAMWISH_API_URL = "https://api.streamwish.com/api/file/list"
STREAMWISH_MAX_FILES = 10_000
STREAMWISH_PAGE_SIZE = 100
MIXDROP_API_URL = "https://api.mixdrop.ag/folderlist"
MIXDROP_MAX_FILES = 10_000
MIXDROP_MAX_FOLDERS = 1_000
MIXDROP_REQUEST_INTERVAL_SECONDS = 0.11
STREAMTAPE_API_URL = "https://api.streamtape.com/file/listfolder"
STREAMTAPE_MAX_FILES = 10_000
STREAMTAPE_MAX_FOLDERS = 1_000
FILELIONS_API_URL = "https://earnvidsapi.com/api/file/list"
FILELIONS_MAX_FILES = 10_000
FILELIONS_PAGE_SIZE = 50
DOODSTREAM_API_URL = "https://doodapi.co/api/file/list"
DOODSTREAM_MAX_FILES = 10_000
DOODSTREAM_PAGE_SIZE = 200
LULUSTREAM_API_URL = "https://lulustream.com/api/file/list"
LULUSTREAM_MAX_FILES = 10_000
LULUSTREAM_PAGE_SIZE = 50
TMDB_TOKEN = re.compile(r"(?:^|[^a-z0-9])tmdb[\s_.:-]*(\d+)(?:$|[^a-z0-9])", re.I)
IMDB_TOKEN = re.compile(r"(?:^|[^a-z0-9])(tt\d{5,12})(?:$|[^a-z0-9])", re.I)
EPISODE_TOKEN = re.compile(r"\bs(\d{1,2})[\s._-]*e(\d{1,3})\b", re.I)
TV_MARKER = re.compile(r"\b(?:s\d{1,2}|season\s*\d{1,2})\b", re.I)
QUALITY_TOKEN = re.compile(r"\b(2160p|1080p|720p|480p|4k)\b", re.I)


class HostLibrarySyncError(RuntimeError):
    """A safe, user-facing failure from an account library sync."""


class AccountLibraryClient(Protocol):
    def list_files(self) -> Iterable[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class AccountLibraryAsset:
    provider_asset_id: str
    title: str
    folder_id: str
    playable: bool
    provider_status: str
    metadata: dict[str, Any]


class StreamWishAccountClient:
    """Small server-side client for StreamWish's account file listing API."""

    def __init__(
        self,
        api_key: str,
        *,
        http_get: Any = requests.get,
        timeout_seconds: int = 15,
    ) -> None:
        self._api_key = str(api_key or "").strip()
        self._http_get = http_get
        self._timeout_seconds = timeout_seconds
        if not self._api_key:
            raise HostLibrarySyncError("StreamWish API key is not configured.")

    def list_files(self) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        page = 1
        while True:
            try:
                response = self._http_get(
                    STREAMWISH_API_URL,
                    params={
                        "key": self._api_key,
                        "page": page,
                        "per_page": STREAMWISH_PAGE_SIZE,
                    },
                    timeout=self._timeout_seconds,
                    allow_redirects=False,
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                raise HostLibrarySyncError("StreamWish library could not be reached.") from exc
            if not isinstance(payload, dict) or int(payload.get("status") or 0) != 200:
                raise HostLibrarySyncError("StreamWish rejected the library sync request.")
            result = payload.get("result")
            page_files = result.get("files") if isinstance(result, dict) else None
            if not isinstance(page_files, list) or not all(isinstance(item, dict) for item in page_files):
                raise HostLibrarySyncError("StreamWish returned an invalid file list.")
            files.extend(page_files)
            if len(files) > STREAMWISH_MAX_FILES:
                raise HostLibrarySyncError("StreamWish library exceeds the 10,000-file sync limit.")
            pages = _positive_int(result.get("pages") if isinstance(result, dict) else None)
            if not page_files or (pages is not None and page >= pages):
                return files
            if pages is None and len(page_files) < STREAMWISH_PAGE_SIZE:
                return files
            page += 1
            if page > STREAMWISH_MAX_FILES:
                raise HostLibrarySyncError("StreamWish pagination did not terminate.")


class MixDropAccountClient:
    """Account-only MixDrop inventory client; it never keeps direct media links."""

    def __init__(
        self,
        api_email: str,
        api_key: str,
        *,
        http_get: Any = requests.get,
        timeout_seconds: int = 15,
        sleep_fn: Any = time.sleep,
        monotonic_fn: Any = time.monotonic,
    ) -> None:
        self._api_email = str(api_email or "").strip()
        self._api_key = str(api_key or "").strip()
        self._http_get = http_get
        self._timeout_seconds = timeout_seconds
        self._sleep_fn = sleep_fn
        self._monotonic_fn = monotonic_fn
        self._last_request_at: float | None = None
        if not self._api_email or not self._api_key:
            raise HostLibrarySyncError("MixDrop API credentials are not configured.")

    def list_files(self) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        folders_to_visit = ["0"]
        visited_folders: set[str] = set()
        while folders_to_visit:
            folder_id = folders_to_visit.pop(0)
            if folder_id in visited_folders:
                continue
            visited_folders.add(folder_id)
            if len(visited_folders) > MIXDROP_MAX_FOLDERS:
                raise HostLibrarySyncError("MixDrop library exceeds the folder sync limit.")
            page = 1
            while True:
                result, pages = self._folder_page(folder_id=folder_id, page=page)
                page_files = result.get("files")
                if not isinstance(page_files, list) or not all(
                    isinstance(item, dict) for item in page_files
                ):
                    raise HostLibrarySyncError("MixDrop returned an invalid file list.")
                for item in page_files:
                    files.append({**item, "_folder_id": folder_id})
                if len(files) > MIXDROP_MAX_FILES:
                    raise HostLibrarySyncError("MixDrop library exceeds the 10,000-file sync limit.")
                folders = result.get("folders")
                if not isinstance(folders, list) or not all(isinstance(item, dict) for item in folders):
                    raise HostLibrarySyncError("MixDrop returned an invalid folder list.")
                for folder in folders:
                    child_id = _text(folder.get("id") or folder.get("folderid"), limit=120)
                    if child_id and child_id not in visited_folders:
                        folders_to_visit.append(child_id)
                if not page_files or (pages is not None and page >= pages):
                    break
                if pages is None:
                    raise HostLibrarySyncError("MixDrop returned a file list without pagination metadata.")
                page += 1
        return files

    def _folder_page(self, *, folder_id: str, page: int) -> tuple[dict[str, Any], int | None]:
        self._respect_rate_limit()
        try:
            response = self._http_get(
                MIXDROP_API_URL,
                params={
                    "email": self._api_email,
                    "key": self._api_key,
                    "id": folder_id,
                    "page": page,
                },
                timeout=self._timeout_seconds,
                allow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise HostLibrarySyncError("MixDrop library could not be reached.") from exc
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise HostLibrarySyncError("MixDrop rejected the library sync request.")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise HostLibrarySyncError("MixDrop returned an invalid library response.")
        return result, _positive_int(payload.get("pages"))

    def _respect_rate_limit(self) -> None:
        now = float(self._monotonic_fn())
        if self._last_request_at is not None:
            remaining = MIXDROP_REQUEST_INTERVAL_SECONDS - (now - self._last_request_at)
            if remaining > 0:
                self._sleep_fn(remaining)
        self._last_request_at = float(self._monotonic_fn())


class StreamTapeAccountClient:
    """Inventory only the folders/files owned by one StreamTape API account."""

    def __init__(
        self,
        api_login: str,
        api_key: str,
        *,
        http_get: Any = requests.get,
        timeout_seconds: int = 15,
    ) -> None:
        self._api_login = str(api_login or "").strip()
        self._api_key = str(api_key or "").strip()
        self._http_get = http_get
        self._timeout_seconds = timeout_seconds
        if not self._api_login or not self._api_key:
            raise HostLibrarySyncError("StreamTape API credentials are not configured.")

    def list_files(self) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        folders_to_visit: list[str | None] = [None]
        visited_folders: set[str] = set()
        while folders_to_visit:
            folder_id = folders_to_visit.pop(0)
            visit_key = folder_id or "__root__"
            if visit_key in visited_folders:
                continue
            visited_folders.add(visit_key)
            if len(visited_folders) > STREAMTAPE_MAX_FOLDERS:
                raise HostLibrarySyncError("StreamTape library exceeds the folder sync limit.")
            result = self._folder(folder_id)
            folders = result.get("folders")
            page_files = result.get("files")
            if not isinstance(folders, list) or not all(isinstance(item, dict) for item in folders):
                raise HostLibrarySyncError("StreamTape returned an invalid folder list.")
            if not isinstance(page_files, list) or not all(isinstance(item, dict) for item in page_files):
                raise HostLibrarySyncError("StreamTape returned an invalid file list.")
            files.extend({**item, "_folder_id": folder_id or ""} for item in page_files)
            if len(files) > STREAMTAPE_MAX_FILES:
                raise HostLibrarySyncError("StreamTape library exceeds the 10,000-file sync limit.")
            for folder in folders:
                child_id = _text(folder.get("id"), limit=120)
                if child_id and child_id not in visited_folders:
                    folders_to_visit.append(child_id)
        return files

    def _folder(self, folder_id: str | None) -> dict[str, Any]:
        params = {"login": self._api_login, "key": self._api_key}
        if folder_id:
            params["folder"] = folder_id
        try:
            response = self._http_get(
                STREAMTAPE_API_URL,
                params=params,
                timeout=self._timeout_seconds,
                allow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise HostLibrarySyncError("StreamTape library could not be reached.") from exc
        if not isinstance(payload, dict) or int(payload.get("status") or 0) != 200:
            raise HostLibrarySyncError("StreamTape rejected the library sync request.")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise HostLibrarySyncError("StreamTape returned an invalid library response.")
        return result


class FileLionsAccountClient:
    """Inventory files owned by the configured FileLions/EarnVids account."""

    def __init__(self, api_key: str, *, http_get: Any = requests.get, timeout_seconds: int = 15) -> None:
        self._api_key = str(api_key or "").strip()
        self._http_get = http_get
        self._timeout_seconds = timeout_seconds
        if not self._api_key:
            raise HostLibrarySyncError("FileLions API key is not configured.")

    def list_files(self) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        page = 1
        while True:
            try:
                response = self._http_get(
                    FILELIONS_API_URL,
                    params={"key": self._api_key, "page": page, "per_page": FILELIONS_PAGE_SIZE},
                    timeout=self._timeout_seconds,
                    allow_redirects=False,
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                raise HostLibrarySyncError("FileLions library could not be reached.") from exc
            if not isinstance(payload, dict) or int(payload.get("status") or 0) != 200:
                raise HostLibrarySyncError("FileLions rejected the library sync request.")
            result = payload.get("result")
            page_files = result.get("files") if isinstance(result, dict) else None
            if not isinstance(page_files, list) or not all(isinstance(item, dict) for item in page_files):
                raise HostLibrarySyncError("FileLions returned an invalid file list.")
            files.extend(page_files)
            if len(files) > FILELIONS_MAX_FILES:
                raise HostLibrarySyncError("FileLions library exceeds the 10,000-file sync limit.")
            pages = _positive_int(result.get("pages") if isinstance(result, dict) else None)
            if not page_files or (pages is not None and page >= pages):
                return files
            if pages is None and len(page_files) < FILELIONS_PAGE_SIZE:
                return files
            page += 1


class DoodStreamAccountClient:
    """Inventory files owned by the configured DoodStream account."""

    def __init__(self, api_key: str, *, http_get: Any = requests.get, timeout_seconds: int = 15) -> None:
        self._api_key = str(api_key or "").strip()
        self._http_get = http_get
        self._timeout_seconds = timeout_seconds
        if not self._api_key:
            raise HostLibrarySyncError("DoodStream API key is not configured.")

    def list_files(self) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        page = 1
        while True:
            try:
                response = self._http_get(
                    DOODSTREAM_API_URL,
                    params={"key": self._api_key, "page": page, "per_page": DOODSTREAM_PAGE_SIZE},
                    timeout=self._timeout_seconds,
                    allow_redirects=False,
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                raise HostLibrarySyncError("DoodStream library could not be reached.") from exc
            if not isinstance(payload, dict) or int(payload.get("status") or 0) != 200:
                raise HostLibrarySyncError("DoodStream rejected the library sync request.")
            result = payload.get("result")
            page_files = result.get("files") if isinstance(result, dict) else None
            if not isinstance(page_files, list) or not all(isinstance(item, dict) for item in page_files):
                raise HostLibrarySyncError("DoodStream returned an invalid file list.")
            files.extend(page_files)
            if len(files) > DOODSTREAM_MAX_FILES:
                raise HostLibrarySyncError("DoodStream library exceeds the 10,000-file sync limit.")
            pages = _positive_int(result.get("total_pages") if isinstance(result, dict) else None)
            if not page_files or (pages is not None and page >= pages):
                return files
            if pages is None and len(page_files) < DOODSTREAM_PAGE_SIZE:
                return files
            page += 1


class LuluStreamAccountClient:
    """Inventory files owned by the configured LuluStream account."""

    def __init__(self, api_key: str, *, http_get: Any = requests.get, timeout_seconds: int = 15) -> None:
        self._api_key = str(api_key or "").strip()
        self._http_get = http_get
        self._timeout_seconds = timeout_seconds
        if not self._api_key:
            raise HostLibrarySyncError("LuluStream API key is not configured.")

    def list_files(self) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        page = 1
        while True:
            try:
                response = self._http_get(
                    LULUSTREAM_API_URL,
                    params={"key": self._api_key, "page": page, "per_page": LULUSTREAM_PAGE_SIZE},
                    timeout=self._timeout_seconds,
                    allow_redirects=False,
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                raise HostLibrarySyncError("LuluStream library could not be reached.") from exc
            if not isinstance(payload, dict) or int(payload.get("status") or 0) != 200:
                raise HostLibrarySyncError("LuluStream rejected the library sync request.")
            result = payload.get("result")
            page_files = result.get("files") if isinstance(result, dict) else None
            if not isinstance(page_files, list) or not all(isinstance(item, dict) for item in page_files):
                raise HostLibrarySyncError("LuluStream returned an invalid file list.")
            files.extend(page_files)
            if len(files) > LULUSTREAM_MAX_FILES:
                raise HostLibrarySyncError("LuluStream library exceeds the 10,000-file sync limit.")
            pages = _positive_int(result.get("pages") if isinstance(result, dict) else None)
            if not page_files or (pages is not None and page >= pages):
                return files
            if pages is None and len(page_files) < LULUSTREAM_PAGE_SIZE:
                return files
            page += 1


@dataclass(frozen=True, slots=True)
class HostLibrarySyncResult:
    batch: ImportBatch
    assets_seen: int
    assets_cached: int


class StreamWishLibrarySyncService:
    provider_key = "streamwish"
    account_key = "default"

    @classmethod
    def sync(cls, client: AccountLibraryClient) -> HostLibrarySyncResult:
        """Mirror a configured account, then pass strict candidates to the catalog pipeline."""
        raw_files = list(client.list_files())
        if len(raw_files) > STREAMWISH_MAX_FILES:
            raise HostLibrarySyncError("StreamWish library exceeds the 10,000-file sync limit.")

        assets: list[AccountLibraryAsset] = []
        for raw in raw_files:
            asset = _streamwish_asset(raw)
            if asset is not None:
                assets.append(asset)

        return AccountLibrarySyncService.sync_assets(
            provider_key=cls.provider_key,
            account_key=cls.account_key,
            source_name="StreamWish account library",
            assets=assets,
            assets_seen=len(raw_files),
        )


class MixDropLibrarySyncService:
    provider_key = "mixdrop"
    account_key = "default"

    @classmethod
    def sync(cls, client: AccountLibraryClient) -> HostLibrarySyncResult:
        raw_files = list(client.list_files())
        if len(raw_files) > MIXDROP_MAX_FILES:
            raise HostLibrarySyncError("MixDrop library exceeds the 10,000-file sync limit.")
        assets = [asset for raw in raw_files if (asset := _mixdrop_asset(raw)) is not None]
        return AccountLibrarySyncService.sync_assets(
            provider_key=cls.provider_key,
            account_key=cls.account_key,
            source_name="MixDrop account library",
            assets=assets,
            assets_seen=len(raw_files),
        )


class StreamTapeLibrarySyncService:
    provider_key = "streamtape"
    account_key = "default"

    @classmethod
    def sync(cls, client: AccountLibraryClient) -> HostLibrarySyncResult:
        raw_files = list(client.list_files())
        if len(raw_files) > STREAMTAPE_MAX_FILES:
            raise HostLibrarySyncError("StreamTape library exceeds the 10,000-file sync limit.")
        assets = [asset for raw in raw_files if (asset := _streamtape_asset(raw)) is not None]
        return AccountLibrarySyncService.sync_assets(
            provider_key=cls.provider_key,
            account_key=cls.account_key,
            source_name="StreamTape account library",
            assets=assets,
            assets_seen=len(raw_files),
        )


class FileLionsLibrarySyncService:
    provider_key = "filelions"
    account_key = "default"

    @classmethod
    def sync(cls, client: AccountLibraryClient) -> HostLibrarySyncResult:
        raw_files = list(client.list_files())
        if len(raw_files) > FILELIONS_MAX_FILES:
            raise HostLibrarySyncError("FileLions library exceeds the 10,000-file sync limit.")
        assets = [asset for raw in raw_files if (asset := _filelions_asset(raw)) is not None]
        return AccountLibrarySyncService.sync_assets(
            provider_key=cls.provider_key,
            account_key=cls.account_key,
            source_name="FileLions account library",
            assets=assets,
            assets_seen=len(raw_files),
        )


class DoodStreamLibrarySyncService:
    provider_key = "doodstream"
    account_key = "default"

    @classmethod
    def sync(cls, client: AccountLibraryClient) -> HostLibrarySyncResult:
        raw_files = list(client.list_files())
        if len(raw_files) > DOODSTREAM_MAX_FILES:
            raise HostLibrarySyncError("DoodStream library exceeds the 10,000-file sync limit.")
        assets = [asset for raw in raw_files if (asset := _doodstream_asset(raw)) is not None]
        return AccountLibrarySyncService.sync_assets(
            provider_key=cls.provider_key,
            account_key=cls.account_key,
            source_name="DoodStream account library",
            assets=assets,
            assets_seen=len(raw_files),
        )


class LuluStreamLibrarySyncService:
    provider_key = "lulustream"
    account_key = "default"

    @classmethod
    def sync(cls, client: AccountLibraryClient) -> HostLibrarySyncResult:
        raw_files = list(client.list_files())
        if len(raw_files) > LULUSTREAM_MAX_FILES:
            raise HostLibrarySyncError("LuluStream library exceeds the 10,000-file sync limit.")
        assets = [asset for raw in raw_files if (asset := _lulustream_asset(raw)) is not None]
        return AccountLibrarySyncService.sync_assets(
            provider_key=cls.provider_key, account_key=cls.account_key,
            source_name="LuluStream account library", assets=assets, assets_seen=len(raw_files),
        )


class AccountLibrarySyncService:
    """Persist one provider account's non-secret inventory and strict mappings."""

    @classmethod
    def sync_assets(
        cls,
        *,
        provider_key: str,
        account_key: str,
        source_name: str,
        assets: list[AccountLibraryAsset],
        assets_seen: int,
    ) -> HostLibrarySyncResult:
        if not assets:
            raise HostLibrarySyncError(f"{source_name} has no valid file codes to sync.")
        now = utc_now()
        for asset in assets:
            cls._upsert_asset(
                provider_key=provider_key,
                account_key=account_key,
                asset=asset,
                seen_at=now,
            )
        batch = CatalogImportService.import_rows(
            [_catalog_row_for_asset(provider_key, asset) for asset in assets],
            import_method="account_api",
            source_name=source_name,
            source_type="account_catalog",
            authorization_status="account_authorized",
        )
        return HostLibrarySyncResult(
            batch=batch,
            assets_seen=assets_seen,
            assets_cached=len(assets),
        )

    @staticmethod
    def _upsert_asset(
        *,
        provider_key: str,
        account_key: str,
        asset: AccountLibraryAsset,
        seen_at: Any,
    ) -> ProviderAccountAsset:
        row = db.session.scalar(
            db.select(ProviderAccountAsset).where(
                ProviderAccountAsset.provider == provider_key,
                ProviderAccountAsset.account_key == account_key,
                ProviderAccountAsset.provider_asset_id == asset.provider_asset_id,
            )
        )
        values = {
            "title": asset.title,
            "folder_id": asset.folder_id,
            "playable": asset.playable,
            "provider_status": asset.provider_status,
            "metadata_json": asset.metadata,
            "last_seen_at": seen_at,
        }
        if row is None:
            row = ProviderAccountAsset(
                provider=provider_key,
                account_key=account_key,
                provider_asset_id=asset.provider_asset_id,
                first_seen_at=seen_at,
                **values,
            )
            db.session.add(row)
        else:
            for field, value in values.items():
                setattr(row, field, value)
        return row


def build_streamwish_account_client(config: dict[str, Any]) -> StreamWishAccountClient:
    if not config.get("DRAGON_STREAMWISH_LIBRARY_SYNC_ENABLED"):
        raise HostLibrarySyncError("StreamWish library sync is disabled in configuration.")
    return StreamWishAccountClient(str(config.get("DRAGON_STREAMWISH_API_KEY") or ""))


def build_mixdrop_account_client(config: dict[str, Any]) -> MixDropAccountClient:
    if not config.get("DRAGON_MIXDROP_LIBRARY_SYNC_ENABLED"):
        raise HostLibrarySyncError("MixDrop library sync is disabled in configuration.")
    return MixDropAccountClient(
        str(config.get("DRAGON_MIXDROP_API_EMAIL") or ""),
        str(config.get("DRAGON_MIXDROP_API_KEY") or ""),
    )


def build_streamtape_account_client(config: dict[str, Any]) -> StreamTapeAccountClient:
    if not config.get("DRAGON_STREAMTAPE_LIBRARY_SYNC_ENABLED"):
        raise HostLibrarySyncError("StreamTape library sync is disabled in configuration.")
    return StreamTapeAccountClient(
        str(config.get("DRAGON_STREAMTAPE_API_LOGIN") or ""),
        str(config.get("DRAGON_STREAMTAPE_API_KEY") or ""),
    )


def build_filelions_account_client(config: dict[str, Any]) -> FileLionsAccountClient:
    if not config.get("DRAGON_FILELIONS_LIBRARY_SYNC_ENABLED"):
        raise HostLibrarySyncError("FileLions library sync is disabled in configuration.")
    return FileLionsAccountClient(str(config.get("DRAGON_FILELIONS_API_KEY") or ""))


def build_doodstream_account_client(config: dict[str, Any]) -> DoodStreamAccountClient:
    if not config.get("DRAGON_DOODSTREAM_LIBRARY_SYNC_ENABLED"):
        raise HostLibrarySyncError("DoodStream library sync is disabled in configuration.")
    return DoodStreamAccountClient(str(config.get("DRAGON_DOODSTREAM_API_KEY") or ""))


def build_lulustream_account_client(config: dict[str, Any]) -> LuluStreamAccountClient:
    if not config.get("DRAGON_LULUSTREAM_LIBRARY_SYNC_ENABLED"):
        raise HostLibrarySyncError("LuluStream library sync is disabled in configuration.")
    return LuluStreamAccountClient(str(config.get("DRAGON_LULUSTREAM_API_KEY") or ""))


def _streamwish_asset(raw: dict[str, Any]) -> AccountLibraryAsset | None:
    spec = indexed_embed_provider_spec("streamwish")
    file_code = _text(raw.get("file_code"), limit=300).lower()
    if spec is None or not file_code or not re.fullmatch(spec.asset_id_pattern, file_code):
        return None
    title = _text(raw.get("title") or raw.get("file_title"), limit=500)
    folder_id = _text(raw.get("fld_id") or raw.get("folder_id"), limit=120)
    playable = _truthy(raw.get("canplay"))
    provider_status = _text(raw.get("status"), limit=80)
    metadata = {
        "length": _text(raw.get("length") or raw.get("file_length"), limit=40),
        "public": _truthy(raw.get("public") or raw.get("file_public")),
        "uploaded": _text(raw.get("uploaded") or raw.get("file_created"), limit=80),
    }
    return AccountLibraryAsset(
        provider_asset_id=file_code,
        title=title,
        folder_id=folder_id,
        playable=playable,
        provider_status=provider_status,
        metadata={key: value for key, value in metadata.items() if value not in {"", False}},
    )


def _mixdrop_asset(raw: dict[str, Any]) -> AccountLibraryAsset | None:
    spec = indexed_embed_provider_spec("mixdrop")
    file_ref = _text(raw.get("fileref"), limit=300)
    if spec is None or not file_ref or not re.fullmatch(spec.asset_id_pattern, file_ref):
        return None
    title = _text(raw.get("title"), limit=500)
    folder_id = _text(raw.get("_folder_id"), limit=120)
    is_video = _truthy(raw.get("isvideo"))
    deleted = _truthy(raw.get("deleted"))
    status = _text(raw.get("status"), limit=80)
    playable = is_video and not deleted and status.lower() in {"ok", "ready"}
    metadata = {
        "size": _text(raw.get("size"), limit=40),
        "uploaded": _text(raw.get("uploaded"), limit=80),
        "is_video": is_video,
        "deleted": deleted,
    }
    return AccountLibraryAsset(
        provider_asset_id=file_ref,
        title=title,
        folder_id=folder_id,
        playable=playable,
        provider_status=status,
        metadata={key: value for key, value in metadata.items() if value not in {"", False}},
    )


def _streamtape_asset(raw: dict[str, Any]) -> AccountLibraryAsset | None:
    spec = indexed_embed_provider_spec("streamtape")
    link_id = _text(raw.get("linkid"), limit=300)
    if spec is None or not link_id or not re.fullmatch(spec.asset_id_pattern, link_id):
        return None
    title = _text(raw.get("name"), limit=500)
    folder_id = _text(raw.get("_folder_id"), limit=120)
    convert_state = _text(raw.get("convert"), limit=80)
    playable = convert_state.lower() == "converted"
    metadata = {
        "size": _text(raw.get("size"), limit=40),
        "created_at": _text(raw.get("created_at"), limit=80),
        "downloads": _text(raw.get("downloads"), limit=40),
    }
    return AccountLibraryAsset(
        provider_asset_id=link_id,
        title=title,
        folder_id=folder_id,
        playable=playable,
        provider_status=convert_state,
        metadata={key: value for key, value in metadata.items() if value},
    )


def _filelions_asset(raw: dict[str, Any]) -> AccountLibraryAsset | None:
    spec = indexed_embed_provider_spec("filelions")
    file_code = _text(raw.get("file_code") or raw.get("filecode"), limit=300)
    if spec is None or not file_code or not re.fullmatch(spec.asset_id_pattern, file_code):
        return None
    title = _text(raw.get("title") or raw.get("file_title"), limit=500)
    folder_id = _text(raw.get("fld_id") or raw.get("file_fld_id"), limit=120)
    playable = _truthy(raw.get("canplay"))
    status = _text(raw.get("status"), limit=80)
    metadata = {
        "length": _text(raw.get("length") or raw.get("file_length"), limit=40),
        "public": _truthy(raw.get("public") or raw.get("file_public")),
        "uploaded": _text(raw.get("uploaded") or raw.get("file_created"), limit=80),
    }
    return AccountLibraryAsset(
        provider_asset_id=file_code,
        title=title,
        folder_id=folder_id,
        playable=playable,
        provider_status=status,
        metadata={key: value for key, value in metadata.items() if value not in {"", False}},
    )


def _doodstream_asset(raw: dict[str, Any]) -> AccountLibraryAsset | None:
    spec = indexed_embed_provider_spec("doodstream")
    file_code = _text(raw.get("file_code") or raw.get("filecode"), limit=300)
    if spec is None or not file_code or not re.fullmatch(spec.asset_id_pattern, file_code):
        return None
    title = _text(raw.get("title"), limit=500)
    folder_id = _text(raw.get("fld_id") or raw.get("folder_id"), limit=120)
    playable = _truthy(raw.get("canplay"))
    metadata = {
        "length": _text(raw.get("length"), limit=40),
        "public": _truthy(raw.get("public")),
        "uploaded": _text(raw.get("uploaded"), limit=80),
    }
    return AccountLibraryAsset(
        provider_asset_id=file_code,
        title=title,
        folder_id=folder_id,
        playable=playable,
        provider_status=_text(raw.get("status"), limit=80),
        metadata={key: value for key, value in metadata.items() if value not in {"", False}},
    )


def _lulustream_asset(raw: dict[str, Any]) -> AccountLibraryAsset | None:
    spec = indexed_embed_provider_spec("lulustream")
    file_code = _text(raw.get("file_code") or raw.get("filecode"), limit=300).lower()
    if spec is None or not file_code or not re.fullmatch(spec.asset_id_pattern, file_code):
        return None
    title = _text(raw.get("title") or raw.get("file_title"), limit=500)
    return AccountLibraryAsset(
        provider_asset_id=file_code, title=title,
        folder_id=_text(raw.get("fld_id") or raw.get("file_fld_id"), limit=120),
        playable=_truthy(raw.get("canplay")), provider_status=_text(raw.get("status"), limit=80),
        metadata={key: value for key, value in {
            "length": _text(raw.get("length") or raw.get("file_length"), limit=40),
            "public": _truthy(raw.get("public") or raw.get("file_public")),
            "uploaded": _text(raw.get("uploaded") or raw.get("file_created"), limit=80),
        }.items() if value not in {"", False}},
    )


def _catalog_row_for_asset(provider_key: str, asset: AccountLibraryAsset) -> dict[str, Any]:
    title = asset.title
    tmdb_match = TMDB_TOKEN.search(title)
    imdb_match = IMDB_TOKEN.search(title)
    episode_match = EPISODE_TOKEN.search(title)
    quality_match = QUALITY_TOKEN.search(title)
    is_tv = bool(episode_match or TV_MARKER.search(title))
    row: dict[str, Any] = {
        "provider": provider_key,
        "provider_asset_id": asset.provider_asset_id,
        "media_type": "tv" if is_tv else "movie",
        "title": title,
        "label": _provider_label(provider_key)
        + (f" · {quality_match.group(1).upper()}" if quality_match else ""),
        "quality": quality_match.group(1).upper() if quality_match else "",
        "asset_playable": asset.playable,
        "folder_id": asset.folder_id,
    }
    if tmdb_match:
        row["tmdb_id"] = tmdb_match.group(1)
    if imdb_match:
        row["imdb_id"] = imdb_match.group(1).lower()
    if episode_match:
        row["season"] = episode_match.group(1)
        row["episode"] = episode_match.group(2)
    return row


def _positive_int(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _text(value: Any, *, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _provider_label(provider_key: str) -> str:
    spec = indexed_embed_provider_spec(provider_key)
    return spec.display_name if spec is not None else provider_key.title()
