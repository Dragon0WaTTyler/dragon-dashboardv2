from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from flask import current_app
from sqlalchemy import select

from app.books.matching import normalize_title
from app.books.models import Book
from app.extensions import db
from app.shared.models import SnapshotRecord
from app.shared.time import utc_now

BOOK_NOTION_DOMAIN = "books"
BOOK_NOTION_SCHEMA_VERSION = "books-notion-progress-v1"
BOOK_NOTION_TIMEOUT_SECONDS = 15

BOOK_STATUS_ALIASES = {
    "dropped": "dropped",
    "drop": "dropped",
    "finished": "finished",
    "read": "finished",
    "reading": "reading",
    "paused": "paused",
    "on hold": "paused",
    "wishlist": "wishlist",
    "want to read": "wishlist",
    "want_to_read": "wishlist",
    "reference": "reference",
}


@dataclass(frozen=True, slots=True)
class BookNotionSyncResult:
    configured: bool
    refreshed: bool
    matched: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    last_error: str = ""
    reason: str = ""


class BookNotionSyncError(RuntimeError):
    pass


class BookNotionSyncClient:
    def __init__(
        self,
        *,
        token: str,
        database_id: str = "",
        data_source_id: str = "",
        session: requests.Session | None = None,
        timeout_seconds: float = BOOK_NOTION_TIMEOUT_SECONDS,
    ) -> None:
        self.token = token.strip()
        self.database_id = database_id.strip().replace("-", "")
        self._configured_data_source_id = data_source_id.strip().replace("-", "")
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": "2025-09-03",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        self._resolved_data_source_id: str | None = None
        self._schema_cache: dict[str, dict] | None = None

    @property
    def configured(self) -> bool:
        return bool(self.token and (self._configured_data_source_id or self.database_id))

    @property
    def data_source_id(self) -> str:
        if self._resolved_data_source_id:
            return self._resolved_data_source_id
        if self._configured_data_source_id:
            self._resolved_data_source_id = self._configured_data_source_id
            return self._resolved_data_source_id
        if not self.database_id:
            raise BookNotionSyncError("The Notion database or data source ID is not configured.")
        payload = self._request("GET", f"/databases/{self.database_id}")
        sources = payload.get("data_sources") or []
        if not sources:
            raise BookNotionSyncError("The Notion database has no accessible data source.")
        self._resolved_data_source_id = str(sources[0]["id"])
        return self._resolved_data_source_id

    def schema(self) -> dict[str, dict]:
        if self._schema_cache is None:
            payload = self._request("GET", f"/data_sources/{self.data_source_id}")
            self._schema_cache = dict(payload.get("properties") or {})
        return self._schema_cache

    def list_books(self) -> list[dict[str, Any]]:
        if not self.configured:
            raise BookNotionSyncError("Notion is not configured.")
        schema = self.schema()
        if not _is_book_schema(schema):
            raise BookNotionSyncError("Configured Notion source is not a books database.")
        pages: list[dict] = []
        cursor: str | None = None
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
        return [self._page_to_book(page) for page in pages if not page.get("in_trash")]

    def _page_to_book(self, page: dict) -> dict[str, Any]:
        properties = page.get("properties") or {}
        schema = self.schema()
        title_name = _title_property_name(schema) or "Name"
        title = _property_value(properties, title_name)
        if not title:
            title = _property_value(properties, "Title")
        page_count = _positive_int(_first_property_value(properties, ("Pages", "Page Count", "Total Pages", "Number of Pages")))
        current_page = _positive_int(
            _first_property_value(
                properties,
                ("Current Page", "Pages Read", "Page Read", "Current"),
            )
        )
        progress_percent = _positive_int(
            _first_property_value(
                properties,
                ("Progress", "Reading Progress", "Progress Percent", "Progress %"),
            )
        )
        if current_page is None and progress_percent is not None and page_count:
            current_page = min(page_count, round(page_count * progress_percent / 100))
        status = _normalize_status(
            _first_property_value(properties, ("Status", "Reading Status", "State"))
        )
        authors = _string_list(
            _first_property_value(properties, ("Authors", "Author", "Writer"))
        )
        cover_url = _page_cover_url(page, properties)
        return {
            "notion_page_id": str(page.get("id") or ""),
            "notion_url": str(page.get("url") or ""),
            "last_edited_time": str(page.get("last_edited_time") or ""),
            "title": str(title or ""),
            "authors": authors,
            "cover_url": cover_url,
            "status": status,
            "page_count": page_count,
            "current_page": current_page,
            "progress_percent": progress_percent,
        }

    def _request(self, method: str, path: str, **kwargs) -> dict:
        if not self.configured:
            raise BookNotionSyncError("Notion is not configured.")
        try:
            response = self.session.request(
                method,
                f"https://api.notion.com/v1{path}",
                timeout=self.timeout_seconds,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise BookNotionSyncError("Notion is unavailable.") from exc
        if response.status_code >= 400:
            try:
                message = str(response.json().get("message") or "")
            except ValueError:
                message = ""
            raise BookNotionSyncError(message or f"Notion returned HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise BookNotionSyncError("Notion returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise BookNotionSyncError("Notion returned an unexpected payload.")
        return payload


class BookNotionSyncService:
    @staticmethod
    def ensure_synced(*, force: bool = False) -> BookNotionSyncResult:
        client = BookNotionSyncService._client()
        if client is None or not getattr(client, "configured", False):
            return BookNotionSyncResult(configured=False, refreshed=False, reason="Not configured.")
        ttl_seconds = int(current_app.config.get("DRAGON_NOTION_SYNC_TTL_SECONDS", 120))
        snapshot = db.session.scalar(
            select(SnapshotRecord).where(SnapshotRecord.domain == BOOK_NOTION_DOMAIN)
        )
        now = utc_now()
        snapshot_updated_at = _as_utc(snapshot.updated_at if snapshot else None)
        if (
            not force
            and snapshot is not None
            and snapshot_updated_at is not None
            and (now - snapshot_updated_at).total_seconds() < ttl_seconds
        ):
            return BookNotionSyncResult(
                configured=True,
                refreshed=False,
                reason="Cached.",
            )
        try:
            items = client.list_books()
            result = BookNotionSyncService._apply(items)
            checksum = _checksum(items)
            snapshot = _upsert_snapshot(
                snapshot,
                checksum=checksum,
                now=now,
                message=(
                    f"{result.created} book row(s) created from Notion; "
                    f"{result.updated} updated; "
                    f"{result.skipped} unmatched."
                ),
            )
            db.session.commit()
            return result
        except BookNotionSyncError as exc:
            _mark_snapshot_failure(snapshot, now=now, message=str(exc))
            db.session.commit()
            return BookNotionSyncResult(
                configured=True,
                refreshed=False,
                last_error=str(exc),
                reason="Sync failed.",
            )

    @staticmethod
    def _client() -> BookNotionSyncClient | Any | None:
        injected = current_app.extensions.get("dragon_book_notion_sync_client")
        if injected is not None:
            return injected
        settings = current_app.extensions.get("dragon_settings")
        if settings is None:
            return None
        if not getattr(settings, "notion_sync_enabled", False):
            return None
        token = str(getattr(settings, "notion_token", "") or "")
        database_id = str(getattr(settings, "book_notion_database_id", "") or "")
        data_source_id = str(getattr(settings, "book_notion_data_source_id", "") or "")
        if not token or not (database_id or data_source_id):
            return None
        return BookNotionSyncClient(
            token=token,
            database_id=database_id,
            data_source_id=data_source_id,
            timeout_seconds=float(BOOK_NOTION_TIMEOUT_SECONDS),
        )

    @staticmethod
    def _apply(items: list[dict[str, Any]]) -> BookNotionSyncResult:
        books = list(db.session.scalars(select(Book)))
        books_by_page_id: dict[str, Book] = {}
        books_by_title: dict[str, list[Book]] = {}
        for book in books:
            notion_page_id = str((book.external_ids or {}).get("notion_page_id") or "")
            if notion_page_id:
                books_by_page_id[notion_page_id] = book
            books_by_title.setdefault(normalize_title(book.title), []).append(book)

        matched = 0
        created = 0
        updated = 0
        skipped = 0
        for item in items:
            book = BookNotionSyncService._match_book(
                item,
                books_by_page_id=books_by_page_id,
                books_by_title=books_by_title,
            )
            if book is None:
                book = BookNotionSyncService._create_book(item)
                if book is None:
                    skipped += 1
                    continue
                db.session.add(book)
                notion_page_id = str((book.external_ids or {}).get("notion_page_id") or "")
                if notion_page_id:
                    books_by_page_id[notion_page_id] = book
                books_by_title.setdefault(normalize_title(book.title), []).append(book)
                created += 1
            else:
                matched += 1
            if BookNotionSyncService._apply_item(book, item):
                updated += 1

        return BookNotionSyncResult(
            configured=True,
            refreshed=True,
            matched=matched,
            created=created,
            updated=updated,
            skipped=skipped,
        )

    @staticmethod
    def _match_book(
        item: dict[str, Any],
        *,
        books_by_page_id: dict[str, Book],
        books_by_title: dict[str, list[Book]],
    ) -> Book | None:
        notion_page_id = str(item.get("notion_page_id") or "").strip()
        if notion_page_id and notion_page_id in books_by_page_id:
            return books_by_page_id[notion_page_id]
        title = normalize_title(str(item.get("title") or ""))
        if not title:
            return None
        matches = books_by_title.get(title, [])
        if len(matches) == 1:
            return matches[0]
        return None

    @staticmethod
    def _apply_item(book: Book, item: dict[str, Any]) -> bool:
        changed = False
        external_ids = dict(book.external_ids or {})
        notion_page_id = str(item.get("notion_page_id") or "").strip()
        if notion_page_id and external_ids.get("notion_page_id") != notion_page_id:
            external_ids["notion_page_id"] = notion_page_id
            book.external_ids = external_ids
            changed = True

        metadata_state = dict(book.metadata_state or {})
        sync_metadata: dict[str, Any] = {}

        page_count = _positive_int(item.get("page_count"))
        current_page = _positive_int(item.get("current_page"))
        progress_percent = _positive_int(item.get("progress_percent"))
        if current_page is None and progress_percent is not None and page_count:
            current_page = min(page_count, round(page_count * progress_percent / 100))
        if page_count is not None and page_count != book.page_count:
            book.page_count = page_count
            changed = True
        if current_page is not None and current_page != book.current_page:
            book.current_page = current_page
            changed = True
        status = _normalize_status(str(item.get("status") or ""))
        if status and status != book.status:
            book.status = status
            changed = True
        cover_url = str(item.get("cover_url") or "").strip()
        if cover_url and cover_url != book.cover_url:
            book.cover_url = cover_url
            changed = True
        if page_count is not None:
            sync_metadata["notion_page_count"] = page_count
        if current_page is not None:
            sync_metadata["notion_current_page"] = current_page
        if progress_percent is not None:
            sync_metadata["notion_progress_percent"] = progress_percent
        if status:
            sync_metadata["notion_status"] = status
        if cover_url:
            sync_metadata["notion_cover_url"] = cover_url
        if sync_metadata:
            if any(metadata_state.get(key) != value for key, value in sync_metadata.items()):
                metadata_state.update(sync_metadata)
                book.metadata_state = metadata_state
                changed = True

        return changed

    @staticmethod
    def _create_book(item: dict[str, Any]) -> Book | None:
        title = " ".join(str(item.get("title") or "").split())
        normalized_title = normalize_title(title)
        if not title or not normalized_title:
            return None
        page_count = _positive_int(item.get("page_count")) or 0
        current_page = _positive_int(item.get("current_page")) or 0
        progress_percent = _positive_int(item.get("progress_percent"))
        if current_page == 0 and progress_percent is not None and page_count:
            current_page = min(page_count, round(page_count * progress_percent / 100))
        status = _normalize_status(str(item.get("status") or "")) or "wishlist"
        notion_page_id = str(item.get("notion_page_id") or "").strip()
        notion_url = str(item.get("notion_url") or "").strip()
        cover_url = str(item.get("cover_url") or "").strip()
        metadata_state: dict[str, Any] = {
            "notion_page_count": page_count,
            "notion_current_page": current_page,
            "notion_status": status,
        }
        if progress_percent is not None:
            metadata_state["notion_progress_percent"] = progress_percent
        if notion_url:
            metadata_state["notion_url"] = notion_url
        if cover_url:
            metadata_state["notion_cover_url"] = cover_url
        return Book(
            title=title,
            normalized_title=normalized_title,
            authors=list(item.get("authors") or []),
            cover_url=cover_url,
            status=status,
            current_page=current_page,
            page_count=page_count,
            source="Notion",
            external_ids={"notion_page_id": notion_page_id} if notion_page_id else {},
            metadata_status="missing",
            metadata_sources=["Notion"],
            metadata_state=metadata_state,
        )


def _upsert_snapshot(
    snapshot: SnapshotRecord | None,
    *,
    checksum: str,
    now: datetime,
    message: str,
) -> SnapshotRecord:
    if snapshot is None:
        snapshot = SnapshotRecord(
            domain=BOOK_NOTION_DOMAIN,
            schema_version=BOOK_NOTION_SCHEMA_VERSION,
            relative_path="notion://books",
            checksum=checksum,
            state="fresh",
            message=message,
            generated_at=now,
            last_success_at=now,
        )
        db.session.add(snapshot)
        return snapshot
    snapshot.schema_version = BOOK_NOTION_SCHEMA_VERSION
    snapshot.relative_path = "notion://books"
    snapshot.checksum = checksum
    snapshot.state = "fresh"
    snapshot.message = message
    snapshot.generated_at = now
    snapshot.last_success_at = now
    return snapshot


def _mark_snapshot_failure(
    snapshot: SnapshotRecord | None,
    *,
    now: datetime,
    message: str,
) -> SnapshotRecord:
    checksum = hashlib.sha256(f"failed:{message}".encode()).hexdigest()
    if snapshot is None:
        snapshot = SnapshotRecord(
            domain=BOOK_NOTION_DOMAIN,
            schema_version=BOOK_NOTION_SCHEMA_VERSION,
            relative_path="notion://books",
            checksum=checksum,
            state="stale",
            message=message,
            generated_at=now,
            last_success_at=now,
        )
        db.session.add(snapshot)
        return snapshot
    snapshot.schema_version = BOOK_NOTION_SCHEMA_VERSION
    snapshot.relative_path = "notion://books"
    snapshot.checksum = checksum
    snapshot.state = "stale"
    snapshot.message = message
    snapshot.generated_at = now
    return snapshot


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _checksum(items: list[dict[str, Any]]) -> str:
    payload = "\n".join(
        "|".join(
            str(item.get(field) or "")
            for field in (
                "notion_page_id",
                "title",
                "cover_url",
                "page_count",
                "current_page",
                "progress_percent",
                "status",
            )
        )
        for item in sorted(
            items,
            key=lambda row: str(row.get("notion_page_id") or row.get("title") or ""),
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _title_property_name(schema: dict[str, dict]) -> str:
    for name, definition in schema.items():
        if str((definition or {}).get("type") or "") == "title":
            return name
    return ""


def _property_value(properties: dict, name: str) -> Any:
    return _decode_property(properties.get(name))


def _first_property_value(properties: dict, names: tuple[str, ...]) -> Any:
    for name in names:
        value = _decode_property(properties.get(name))
        if value not in (None, "", []):
            return value
    return None


def _page_cover_url(page: dict, properties: dict) -> str:
    url = _notion_file_url(page.get("cover"))
    if url:
        return url
    exact_names = ("cover", "Cover", "Image", "Thumbnail", "Poster", "Artwork")
    for name in exact_names:
        url = _cover_property_url(properties.get(name))
        if url:
            return url
    for name, prop in properties.items():
        normalized_name = normalize_title(name)
        if any(
            token in normalized_name
            for token in ("cover", "image", "thumbnail", "poster", "artwork")
        ):
            url = _cover_property_url(prop)
            if url:
                return url
    return ""


def _cover_property_url(prop: object) -> str:
    if not isinstance(prop, dict):
        return ""
    prop_type = str(prop.get("type") or "").strip()
    if prop_type == "files":
        for item in prop.get("files") or []:
            url = _notion_file_url(item)
            if url:
                return url
        return ""
    value = _decode_property(prop)
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    return ""


def _notion_file_url(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    file_type = str(value.get("type") or "").strip()
    payload = value.get(file_type)
    if isinstance(payload, dict):
        return str(payload.get("url") or "").strip()
    return ""


def _decode_property(prop: object) -> Any:
    if not isinstance(prop, dict):
        return None
    prop_type = str(prop.get("type") or "").strip()
    value = prop.get(prop_type)
    if prop_type in {"title", "rich_text"} and isinstance(value, list):
        return "".join(
            str(part.get("plain_text") or "")
            for part in value
            if isinstance(part, dict)
        ).strip()
    if prop_type == "number":
        return value
    if prop_type == "checkbox":
        return bool(value)
    if prop_type in {"select", "status"} and isinstance(value, dict):
        return str(value.get("name") or "").strip()
    if prop_type == "date" and isinstance(value, dict):
        return str(value.get("start") or "").strip()
    if prop_type in {"url", "email", "phone_number"}:
        return str(value or "").strip()
    if prop_type == "formula" and isinstance(value, dict):
        formula_type = str(value.get("type") or "").strip()
        return value.get(formula_type)
    if prop_type == "multi_select" and isinstance(value, list):
        return ", ".join(
            str(option.get("name") or "").strip()
            for option in value
            if isinstance(option, dict) and str(option.get("name") or "").strip()
        )
    return None


def _is_book_schema(schema: dict[str, dict]) -> bool:
    names = {normalize_title(name) for name in schema}
    book_signals = {
        "author",
        "authors",
        "book",
        "pages",
        "page count",
        "pages read",
        "current page",
        "kindle progress",
        "isbn",
    }
    movie_signals = {"tmdb id", "media type", "director", "season", "episode"}
    return bool(names & book_signals) and not bool(names & movie_signals - {"media type"})


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _normalize_status(value: str) -> str:
    text = normalize_title(value)
    if not text:
        return ""
    return BOOK_STATUS_ALIASES.get(text, text)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        return [part for part in parts if part]
    if value in (None, ""):
        return []
    text = str(value).strip()
    return [text] if text else []
