from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from flask import current_app

from app.books.clippings import KindleClippingMatch, match_clipping_payload
from app.books.kindle_sync import (
    KINDLE_NOTION_TIMEOUT_SECONDS,
    KindleSyncCredentialStore,
    KindleSyncValidationError,
)
from app.books.repositories import BookRepository
from app.shared.text import text_direction
from app.shared.time import utc_iso


@dataclass(frozen=True, slots=True)
class BookQuotesSnapshotItem:
    notion_page_id: str
    payload: dict
    notion_url: str = ""
    last_edited_time: str = ""

    def as_dict(self) -> dict:
        return {
            "notion_page_id": self.notion_page_id,
            "payload": self.payload,
            "notion_url": self.notion_url,
            "last_edited_time": self.last_edited_time,
        }

    @staticmethod
    def from_dict(payload: Mapping | None) -> BookQuotesSnapshotItem:
        payload = payload or {}
        return BookQuotesSnapshotItem(
            notion_page_id=str(payload.get("notion_page_id") or ""),
            payload=dict(payload.get("payload") or {}),
            notion_url=str(payload.get("notion_url") or ""),
            last_edited_time=str(payload.get("last_edited_time") or ""),
        )


@dataclass(frozen=True, slots=True)
class BookQuotesSnapshot:
    refreshed_at: str = ""
    last_checked_at: str = ""
    last_error: str = ""
    items: tuple[BookQuotesSnapshotItem, ...] = ()

    def as_dict(self) -> dict:
        return {
            "refreshed_at": self.refreshed_at,
            "last_checked_at": self.last_checked_at,
            "last_error": self.last_error,
            "items": [item.as_dict() for item in self.items],
        }

    @staticmethod
    def from_dict(payload: Mapping | None) -> BookQuotesSnapshot:
        payload = payload or {}
        return BookQuotesSnapshot(
            refreshed_at=str(payload.get("refreshed_at") or ""),
            last_checked_at=str(payload.get("last_checked_at") or ""),
            last_error=str(payload.get("last_error") or ""),
            items=tuple(
                BookQuotesSnapshotItem.from_dict(item)
                for item in payload.get("items", [])
                if isinstance(item, Mapping)
            ),
        )


@dataclass(frozen=True, slots=True)
class BookQuotesProjection:
    item: BookQuotesSnapshotItem
    match: KindleClippingMatch


@dataclass(frozen=True, slots=True)
class BookQuotesRefreshResult:
    snapshot: BookQuotesSnapshot
    refreshed: bool
    fetched: int
    matched: int
    ambiguous: int
    needs_review: int


@dataclass(frozen=True, slots=True)
class BookQuotesSnapshotAssignResult:
    snapshot: BookQuotesSnapshot
    updated: bool


@dataclass(frozen=True, slots=True)
class BookQuotesSnapshotClearResult:
    snapshot: BookQuotesSnapshot
    cleared: bool


class BookQuotesSnapshotStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def load(self) -> BookQuotesSnapshot:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return BookQuotesSnapshot()
        except (OSError, json.JSONDecodeError):
            return BookQuotesSnapshot()
        if not isinstance(payload, Mapping):
            return BookQuotesSnapshot()
        return BookQuotesSnapshot.from_dict(payload)

    def save(self, snapshot: BookQuotesSnapshot | Mapping) -> None:
        current = (
            snapshot
            if isinstance(snapshot, BookQuotesSnapshot)
            else BookQuotesSnapshot.from_dict(snapshot)
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(current.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    def assign_book(
        self, item_key: str, book: object
    ) -> BookQuotesSnapshotAssignResult:
        result = assign_book_quote_snapshot(self.load(), item_key=item_key, book=book)
        if result.updated:
            self.save(result.snapshot)
        return result

    def clear_local_match(self, item_key: str) -> BookQuotesSnapshotClearResult:
        result = clear_book_quote_local_match(self.load(), item_key=item_key)
        if result.cleared:
            self.save(result.snapshot)
        return result


class BookQuotesSnapshotService:
    @staticmethod
    def store() -> BookQuotesSnapshotStore:
        return _snapshot_store()

    @staticmethod
    def refresh(
        *,
        session=None,
        timeout_seconds: float = KINDLE_NOTION_TIMEOUT_SECONDS,
    ) -> BookQuotesRefreshResult:
        store = _snapshot_store()
        current = store.load()
        checked_at = utc_iso()
        try:
            client = _credential_store().book_quotes_client(
                session=session,
                timeout_seconds=timeout_seconds,
            )
            current_by_page_id = {
                item.notion_page_id: item for item in current.items if item.notion_page_id
            }
            current_by_hash = {
                str(item.payload.get("unique_hash") or ""): item
                for item in current.items
                if str(item.payload.get("unique_hash") or "")
            }
            items: list[BookQuotesSnapshotItem] = []
            for page in client.list_quote_pages():
                payload = client.quote_payload_from_page(page)
                previous = current_by_page_id.get(str(page.get("id") or "")) or current_by_hash.get(
                    str(payload.get("unique_hash") or "")
                )
                items.append(
                    BookQuotesSnapshotItem(
                        notion_page_id=str(page.get("id") or ""),
                        payload=_merge_local_review_payload(previous, payload),
                        notion_url=str(page.get("url") or ""),
                        last_edited_time=str(page.get("last_edited_time") or ""),
                    )
                )
            items = tuple(items)
        except KindleSyncValidationError as exc:
            failed_snapshot = BookQuotesSnapshot(
                refreshed_at=current.refreshed_at,
                last_checked_at=checked_at,
                last_error=str(exc),
                items=current.items,
            )
            store.save(failed_snapshot)
            return _refresh_result(failed_snapshot, refreshed=False)

        refreshed_snapshot = BookQuotesSnapshot(
            refreshed_at=checked_at,
            last_checked_at=checked_at,
            last_error="",
            items=items,
        )
        store.save(refreshed_snapshot)
        return _refresh_result(refreshed_snapshot, refreshed=True)

    @staticmethod
    def status(*, books: Iterable[object] | None = None) -> dict[str, object]:
        snapshot = _snapshot_store().load()
        local_books = tuple(books) if books is not None else tuple(BookRepository.list())
        projections = project_book_quotes(snapshot, local_books)
        counts = Counter(item.match.state for item in projections)
        return {
            "configured": _book_quotes_configured(),
            "refreshed_at": snapshot.refreshed_at,
            "last_checked_at": snapshot.last_checked_at,
            "last_error": snapshot.last_error,
            "item_count": len(snapshot.items),
            "matched": counts.get("matched", 0),
            "ambiguous": counts.get("ambiguous", 0),
            "needs_review": counts.get("needs_review", 0),
            "queue": [
                {
                    "id": _snapshot_item_key(item.item),
                    "title": str(
                        item.item.payload.get("book_title")
                        or item.item.payload.get("quote")
                        or "Book Quote"
                    ),
                    "url": _book_quotes_queue_url(item),
                    "state": item.match.state,
                    "note": item.match.note or str(item.item.payload.get("author") or "Unknown"),
                }
                for item in projections
                if item.match.state != "matched"
            ][:8],
        }

    @staticmethod
    def review_view(
        *,
        books: Iterable[object] | None = None,
        state_filter: str = "all",
        query: str = "",
    ) -> dict[str, object]:
        snapshot = _snapshot_store().load()
        local_books = tuple(books) if books is not None else tuple(BookRepository.list())
        projections = project_book_quotes(snapshot, local_books)
        counts = Counter(item.match.state for item in projections)
        query = " ".join(str(query or "").split())
        filtered = [
            item
            for item in projections
            if _matches_review_filter(item, state_filter=state_filter)
            and _matches_review_query(item, query=query)
        ]
        return {
            "snapshot_count": len(projections),
            "filtered_count": len(filtered),
            "matched_count": counts.get("matched", 0),
            "ambiguous_count": counts.get("ambiguous", 0),
            "needs_review_count": counts.get("needs_review", 0),
            "review_count": counts.get("ambiguous", 0) + counts.get("needs_review", 0),
            "active_filter": state_filter,
            "query": query,
            "refreshed_at": snapshot.refreshed_at,
            "last_checked_at": snapshot.last_checked_at,
            "last_error": snapshot.last_error,
            "configured": _book_quotes_configured(),
            "rows": [_review_row(item) for item in filtered],
            "filters": [
                {"key": "all", "label": "All", "count": len(projections)},
                {
                    "key": "review",
                    "label": "Review",
                    "count": counts.get("ambiguous", 0) + counts.get("needs_review", 0),
                },
                {"key": "matched", "label": "Matched", "count": counts.get("matched", 0)},
                {
                    "key": "ambiguous",
                    "label": "Ambiguous",
                    "count": counts.get("ambiguous", 0),
                },
                {
                    "key": "needs_review",
                    "label": "Needs review",
                    "count": counts.get("needs_review", 0),
                },
            ],
            "book_options": [
                {
                    "id": book.id,
                    "title": book.title,
                    "authors": ", ".join(book.authors),
                }
                for book in local_books
            ],
        }

    @staticmethod
    def highlights_view(
        *,
        books: Iterable[object] | None = None,
        query: str = "",
        book_id: str = "",
    ) -> dict[str, object]:
        snapshot = _snapshot_store().load()
        local_books = tuple(books) if books is not None else tuple(BookRepository.list())
        status = BookQuotesSnapshotService.status(books=local_books)
        matched = _matched_highlights_by_book(snapshot, local_books)
        rows = sorted(
            [
                _highlight_row(book, projection)
                for book, projections in matched.items()
                for projection in projections
            ],
            key=_highlight_sort_key,
            reverse=True,
        )
        query = " ".join(str(query or "").split())
        selected_book_id = str(book_id or "").strip()
        filtered = [
            row
            for row in rows
            if (not selected_book_id or row["book_id"] == selected_book_id)
            and _matches_highlight_query(row, query=query)
        ]
        return {
            "snapshot_count": status["item_count"],
            "matched_count": len(rows),
            "filtered_count": len(filtered),
            "review_count": int(status["ambiguous"]) + int(status["needs_review"]),
            "book_count": len({row["book_id"] for row in rows if row["book_id"]}),
            "query": query,
            "book_id": selected_book_id,
            "refreshed_at": snapshot.refreshed_at,
            "last_checked_at": snapshot.last_checked_at,
            "last_error": snapshot.last_error,
            "configured": bool(status["configured"]),
            "rows": filtered,
            "book_options": [
                {
                    "id": str(getattr(book, "id", "") or ""),
                    "title": str(getattr(book, "title", "") or "Untitled book"),
                    "authors": ", ".join(getattr(book, "authors", ()) or ()),
                    "count": sum(
                        1
                        for row in rows
                        if row["book_id"] == str(getattr(book, "id", "") or "")
                    ),
                }
                for book in sorted(
                    matched.keys(),
                    key=lambda item: str(getattr(item, "title", "") or "").casefold(),
                )
            ],
        }

    @staticmethod
    def book_highlights(book: object) -> list[dict[str, object]]:
        books = tuple(BookRepository.list())
        snapshot = _snapshot_store().load()
        highlights = [
            _highlight_payload(item)
            for item in project_book_quotes(snapshot, books)
            if item.match.book_id == str(getattr(book, "id", "") or "")
            and str(item.item.payload.get("quote") or "").strip()
        ]
        return sorted(
            highlights,
            key=lambda item: (
                str(item.get("created_at") or ""),
                str(item.get("id") or ""),
            ),
            reverse=True,
        )

    @staticmethod
    def book_highlight_counts(
        books: Iterable[object] | None = None,
    ) -> dict[str, int]:
        local_books = tuple(books) if books is not None else tuple(BookRepository.list())
        return {
            str(getattr(book, "id", "") or ""): len(items)
            for book, items in _matched_highlights_by_book(
                _snapshot_store().load(),
                local_books,
            ).items()
        }


def project_book_quotes(
    snapshot: BookQuotesSnapshot | Mapping,
    books: Iterable[object],
) -> tuple[BookQuotesProjection, ...]:
    current = (
        snapshot
        if isinstance(snapshot, BookQuotesSnapshot)
        else BookQuotesSnapshot.from_dict(snapshot)
    )
    local_books = tuple(books)
    return tuple(
        BookQuotesProjection(
            item=item,
            match=match_clipping_payload(item.payload, local_books),
        )
        for item in current.items
    )


def assign_book_quote_snapshot(
    snapshot: BookQuotesSnapshot | Mapping,
    *,
    item_key: str,
    book: object,
) -> BookQuotesSnapshotAssignResult:
    current = _snapshot(snapshot)
    target_key = str(item_key or "")
    items: list[BookQuotesSnapshotItem] = []
    updated = False
    for item in current.items:
        if _snapshot_item_key(item) != target_key:
            items.append(item)
            continue
        updated = True
        payload = dict(item.payload)
        payload.update(
            {
                "book_id": str(getattr(book, "id", "") or ""),
                "dragon_book_id": str(getattr(book, "dragon_book_id", "") or ""),
                "matched_book_title": str(getattr(book, "title", "") or ""),
                "match_source": "manual_local_review",
            }
        )
        items.append(
            BookQuotesSnapshotItem(
                notion_page_id=item.notion_page_id,
                payload=payload,
                notion_url=item.notion_url,
                last_edited_time=item.last_edited_time,
            )
        )
    return BookQuotesSnapshotAssignResult(
        snapshot=BookQuotesSnapshot(
            refreshed_at=current.refreshed_at,
            last_checked_at=current.last_checked_at,
            last_error=current.last_error,
            items=tuple(items),
        ),
        updated=updated,
    )


def clear_book_quote_local_match(
    snapshot: BookQuotesSnapshot | Mapping,
    *,
    item_key: str,
) -> BookQuotesSnapshotClearResult:
    current = _snapshot(snapshot)
    target_key = str(item_key or "")
    items: list[BookQuotesSnapshotItem] = []
    cleared = False
    for item in current.items:
        if _snapshot_item_key(item) != target_key:
            items.append(item)
            continue
        payload = dict(item.payload)
        if str(payload.get("match_source") or "") == "manual_local_review":
            for key in ("book_id", "dragon_book_id", "matched_book_title", "match_source"):
                payload.pop(key, None)
            cleared = True
        items.append(
            BookQuotesSnapshotItem(
                notion_page_id=item.notion_page_id,
                payload=payload,
                notion_url=item.notion_url,
                last_edited_time=item.last_edited_time,
            )
        )
    return BookQuotesSnapshotClearResult(
        snapshot=BookQuotesSnapshot(
            refreshed_at=current.refreshed_at,
            last_checked_at=current.last_checked_at,
            last_error=current.last_error,
            items=tuple(items),
        ),
        cleared=cleared,
    )


def _refresh_result(
    snapshot: BookQuotesSnapshot,
    *,
    refreshed: bool,
) -> BookQuotesRefreshResult:
    books = tuple(BookRepository.list())
    projections = project_book_quotes(snapshot, books)
    counts = Counter(item.match.state for item in projections)
    return BookQuotesRefreshResult(
        snapshot=snapshot,
        refreshed=refreshed,
        fetched=len(snapshot.items),
        matched=counts.get("matched", 0),
        ambiguous=counts.get("ambiguous", 0),
        needs_review=counts.get("needs_review", 0),
    )


def _book_quotes_configured() -> bool:
    status = _credential_store().status()
    return bool(status.token_configured and status.target_id_configured)


def _snapshot(snapshot: BookQuotesSnapshot | Mapping) -> BookQuotesSnapshot:
    if isinstance(snapshot, BookQuotesSnapshot):
        return snapshot
    return BookQuotesSnapshot.from_dict(snapshot)


def _snapshot_item_key(item: BookQuotesSnapshotItem) -> str:
    return (
        str(item.notion_page_id or "")
        or str(item.payload.get("unique_hash") or "")
        or str(item.payload.get("quote") or "")
    )


def _matches_review_filter(
    projection: BookQuotesProjection, *, state_filter: str
) -> bool:
    selected = str(state_filter or "all").strip().casefold()
    if selected == "all":
        return True
    if selected == "review":
        return projection.match.state in {"needs_review", "ambiguous"}
    return projection.match.state == selected


def _matches_review_query(
    projection: BookQuotesProjection, *, query: str
) -> bool:
    phrase = str(query or "").strip().casefold()
    if not phrase:
        return True
    haystacks = [
        projection.item.payload.get("book_title"),
        projection.item.payload.get("quote"),
        projection.item.payload.get("author"),
        projection.match.book_title,
        projection.match.note,
        projection.item.payload.get("location"),
        projection.item.payload.get("page"),
    ]
    return any(phrase in str(value or "").casefold() for value in haystacks)


def _review_row(projection: BookQuotesProjection) -> dict[str, object]:
    payload = projection.item.payload
    return {
        "id": _snapshot_item_key(projection.item),
        "notion_page_id": projection.item.notion_page_id,
        "notion_url": projection.item.notion_url,
        "title": str(payload.get("book_title") or "Untitled book"),
        "quote": str(payload.get("quote") or ""),
        "author": str(payload.get("author") or "Unknown author"),
        "kind": str(payload.get("kind") or "highlight"),
        "location": str(payload.get("location") or ""),
        "page": str(payload.get("page") or ""),
        "created_at": str(payload.get("created_at") or ""),
        "imported_at": str(payload.get("imported_at") or ""),
        "match": projection.match,
        "match_source": str(payload.get("match_source") or ""),
        "manual_local_match": str(payload.get("match_source") or "") == "manual_local_review",
    }


def _highlight_payload(projection: BookQuotesProjection) -> dict[str, object]:
    payload = projection.item.payload
    return {
        "id": _snapshot_item_key(projection.item),
        "text": str(payload.get("quote") or ""),
        "page": str(payload.get("page") or ""),
        "location": str(payload.get("location") or ""),
        "created_at": str(payload.get("created_at") or ""),
        "imported_at": str(payload.get("imported_at") or ""),
        "source": str(payload.get("source") or "Kindle"),
        "kind": str(payload.get("kind") or "highlight"),
        "direction": text_direction(str(payload.get("quote") or "")),
        "notion_url": projection.item.notion_url,
    }


def _highlight_row(book: object, projection: BookQuotesProjection) -> dict[str, object]:
    payload = projection.item.payload
    return {
        **_highlight_payload(projection),
        "book_id": str(getattr(book, "id", "") or ""),
        "book_title": str(getattr(book, "title", "") or "Untitled book"),
        "book_authors": ", ".join(getattr(book, "authors", ()) or ()) or "Unknown author",
        "source_title": str(payload.get("book_title") or ""),
        "source_author": str(payload.get("author") or ""),
    }


def _highlight_sort_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("created_at") or ""),
        str(row.get("imported_at") or ""),
        str(row.get("id") or ""),
    )


def _matches_highlight_query(row: Mapping[str, object], *, query: str) -> bool:
    phrase = str(query or "").strip().casefold()
    if not phrase:
        return True
    haystacks = [
        row.get("text"),
        row.get("book_title"),
        row.get("book_authors"),
        row.get("source_title"),
        row.get("source_author"),
        row.get("location"),
        row.get("page"),
        row.get("kind"),
    ]
    return any(phrase in str(value or "").casefold() for value in haystacks)


def _merge_local_review_payload(
    existing: BookQuotesSnapshotItem | None,
    payload: Mapping | None,
) -> dict:
    current = dict(payload or {})
    if existing is None:
        return current
    existing_payload = dict(existing.payload or {})
    if str(existing_payload.get("match_source") or "") != "manual_local_review":
        return current
    if current.get("book_id") or current.get("matched_book_id") or current.get("dragon_book_id"):
        return current
    for key in ("book_id", "dragon_book_id", "matched_book_title", "match_source"):
        value = existing_payload.get(key)
        if value:
            current[key] = value
    return current


def _book_quotes_queue_url(projection: BookQuotesProjection) -> str:
    if projection.match.state == "ambiguous":
        return "/settings/knowledge/book-quotes?state=ambiguous"
    if projection.match.state == "needs_review":
        return "/settings/knowledge/book-quotes?state=review"
    return "/settings/knowledge/book-quotes"


def _matched_highlights_by_book(
    snapshot: BookQuotesSnapshot | Mapping,
    books: Iterable[object],
) -> dict[object, list[BookQuotesProjection]]:
    matched: dict[object, list[BookQuotesProjection]] = {
        book: [] for book in books if str(getattr(book, "id", "") or "")
    }
    books_by_id = {
        str(getattr(book, "id", "") or ""): book
        for book in books
        if str(getattr(book, "id", "") or "")
    }
    for projection in project_book_quotes(snapshot, tuple(books_by_id.values())):
        book = books_by_id.get(projection.match.book_id)
        if book is None:
            continue
        if not str(projection.item.payload.get("quote") or "").strip():
            continue
        matched.setdefault(book, []).append(projection)
    return matched


def _snapshot_store() -> BookQuotesSnapshotStore:
    return BookQuotesSnapshotStore(
        Path(current_app.instance_path) / "knowledge" / "book_quotes_snapshot.json"
    )


def _credential_store() -> KindleSyncCredentialStore:
    instance_root = Path(current_app.instance_path)
    return KindleSyncCredentialStore(
        token_path=instance_root / "secrets" / "kindle_book_quotes_token",
        metadata_path=instance_root / "knowledge" / "kindle_sync_credentials.json",
    )
