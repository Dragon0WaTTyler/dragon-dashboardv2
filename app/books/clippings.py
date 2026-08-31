from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.books.matching import normalize_title
from app.shared.time import utc_iso
from app.vault.integrations import (
    integration_settings,
    personal_workspace_active,
    update_integration_settings,
)

ENTRY_DELIMITER = re.compile(r"^\s*={5,}\s*$", re.MULTILINE)
META_PATTERN = re.compile(
    r"^-\s+Your\s+(?P<kind>Highlight|Note|Bookmark)\s+"
    r"(?P<position>.*?)\s*\|\s*Added on\s+(?P<created_at>.+)$",
    re.IGNORECASE,
)
PAGE_PATTERN = re.compile(r"\bpage\s+([A-Za-z0-9-]+)", re.IGNORECASE)
LOCATION_PATTERN = re.compile(r"\blocation\s+([A-Za-z0-9-]+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class KindleClipping:
    book_title: str
    author: str
    kind: str
    page: str
    location: str
    created_at: str
    text: str
    unique_hash: str

    def as_book_quote_payload(self) -> dict:
        return {
            "quote": self.text,
            "book_title": self.book_title,
            "author": self.author,
            "page": self.page,
            "location": self.location,
            "created_at": self.created_at,
            "source": "Kindle",
            "unique_hash": self.unique_hash,
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class KindleClippingsParseResult:
    clippings: list[KindleClipping]
    skipped: int


@dataclass(frozen=True, slots=True)
class KindleClippingsOutboxItem:
    unique_hash: str
    payload: dict
    attempts: int = 0
    last_error: str = ""
    last_error_at: str = ""

    def as_dict(self) -> dict:
        return {
            "unique_hash": self.unique_hash,
            "payload": self.payload,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
        }


@dataclass(frozen=True, slots=True)
class KindleClippingsSyncState:
    synced_hashes: frozenset[str] = frozenset()
    pending: tuple[KindleClippingsOutboxItem, ...] = ()

    @staticmethod
    def from_dict(payload: Mapping | None) -> KindleClippingsSyncState:
        payload = payload or {}
        synced = frozenset(str(value) for value in payload.get("synced_hashes", []))
        pending = tuple(
            _outbox_item_from_dict(item)
            for item in payload.get("pending", [])
            if isinstance(item, Mapping)
        )
        return KindleClippingsSyncState(synced_hashes=synced, pending=pending)

    def as_dict(self) -> dict:
        return {
            "synced_hashes": sorted(self.synced_hashes),
            "pending": [item.as_dict() for item in self.pending],
        }


@dataclass(frozen=True, slots=True)
class KindleClippingsQueueResult:
    state: KindleClippingsSyncState
    queued: list[KindleClippingsOutboxItem]
    parsed: int
    skipped_malformed: int
    skipped_synced: int
    skipped_pending: int
    skipped_duplicate: int


@dataclass(frozen=True, slots=True)
class KindleClippingsUploadResult:
    state: KindleClippingsSyncState
    uploaded: int
    missing: int


@dataclass(frozen=True, slots=True)
class KindleClippingsFailureResult:
    state: KindleClippingsSyncState
    failed: int
    missing: int


@dataclass(frozen=True, slots=True)
class KindleClippingsAssignResult:
    state: KindleClippingsSyncState
    updated: bool


@dataclass(frozen=True, slots=True)
class KindleClippingsRemoveResult:
    state: KindleClippingsSyncState
    removed: bool


@dataclass(frozen=True, slots=True)
class KindleClippingsBulkRemoveResult:
    state: KindleClippingsSyncState
    removed: int


@dataclass(frozen=True, slots=True)
class KindleClippingsResetFailuresResult:
    state: KindleClippingsSyncState
    reset: int


@dataclass(frozen=True, slots=True)
class KindleClippingMatch:
    state: str
    confidence: str
    book_id: str = ""
    dragon_book_id: str = ""
    book_title: str = ""
    note: str = ""


@dataclass(frozen=True, slots=True)
class KindleClippingOutboxProjection:
    item: KindleClippingsOutboxItem
    match: KindleClippingMatch


class KindleClippingsStateStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def load(self) -> KindleClippingsSyncState:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return KindleClippingsSyncState()
        except (OSError, json.JSONDecodeError):
            _quarantine_state_file(self.path)
            return KindleClippingsSyncState()
        if not isinstance(payload, Mapping):
            _quarantine_state_file(self.path)
            return KindleClippingsSyncState()
        return KindleClippingsSyncState.from_dict(payload)

    def save(self, state: KindleClippingsSyncState | Mapping) -> None:
        current = _sync_state(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(current.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    def queue_raw(self, raw_text: str) -> KindleClippingsQueueResult:
        result = queue_my_clippings(raw_text, self.load())
        self.save(result.state)
        return result

    def assign_book(
        self, unique_hash: str, book: object
    ) -> KindleClippingsAssignResult:
        result = assign_clipping_book(self.load(), unique_hash=unique_hash, book=book)
        if result.updated:
            self.save(result.state)
        return result

    def remove(self, unique_hash: str) -> KindleClippingsRemoveResult:
        result = remove_clipping_from_outbox(self.load(), unique_hash=unique_hash)
        if result.removed:
            self.save(result.state)
        return result

    def remove_many(self, unique_hashes: Iterable[str]) -> KindleClippingsBulkRemoveResult:
        result = remove_clippings_from_outbox(self.load(), unique_hashes=unique_hashes)
        if result.removed:
            self.save(result.state)
        return result

    def reset_failures(
        self, unique_hashes: Iterable[str]
    ) -> KindleClippingsResetFailuresResult:
        result = reset_clipping_failures(self.load(), unique_hashes=unique_hashes)
        if result.reset:
            self.save(result.state)
        return result


class WorkspaceKindleClippingsStateStore(KindleClippingsStateStore):
    """Persist one user's clipping queue inside their synced workspace cache."""

    def __init__(self) -> None:
        # Queue and review helpers are inherited; storage is WorkspaceIntegration.
        pass

    def load(self) -> KindleClippingsSyncState:
        settings = integration_settings("kindle_clippings")
        return KindleClippingsSyncState.from_dict(settings.get("state"))

    def save(self, state: KindleClippingsSyncState | Mapping) -> None:
        current = _sync_state(state)
        settings = integration_settings("kindle_clippings")
        settings["state"] = current.as_dict()
        update_integration_settings("kindle_clippings", settings)


def workspace_aware_clippings_store(path: Path | str) -> KindleClippingsStateStore:
    """Use legacy disk state only when no personal workspace is active."""

    if personal_workspace_active():
        return WorkspaceKindleClippingsStateStore()
    return KindleClippingsStateStore(path)


def _quarantine_state_file(path: Path) -> Path | None:
    try:
        if not path.exists():
            return None
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = path.with_name(f"{path.name}.corrupt-{stamp}")
        counter = 1
        while target.exists():
            target = path.with_name(f"{path.name}.corrupt-{stamp}-{counter}")
            counter += 1
        path.replace(target)
    except OSError:
        return None
    return target


def project_clippings_outbox(
    state: KindleClippingsSyncState | Mapping, books: Iterable[object]
) -> tuple[KindleClippingOutboxProjection, ...]:
    local_books = tuple(books)
    return tuple(
        KindleClippingOutboxProjection(
            item=item,
            match=match_clipping_payload(item.payload, local_books),
        )
        for item in _sync_state(state).pending
    )


def match_clipping_payload(
    payload: Mapping, books: Iterable[object]
) -> KindleClippingMatch:
    local_books = tuple(books)
    relation = _match_existing_relation(payload, local_books)
    if relation is not None:
        return relation

    clip_title = normalize_title(str(payload.get("book_title") or ""))
    clip_author = normalize_title(str(payload.get("author") or ""))
    if not clip_title:
        return KindleClippingMatch(
            state="needs_review",
            confidence="missing_title",
            note="Malformed clipping",
        )

    title_matches = [
        book for book in local_books if clip_title in _book_title_keys(book)
    ]
    alias_matches = [
        book for book in local_books if clip_title in _book_alias_keys(book)
    ]
    author_matches = [
        book
        for book in (*alias_matches, *title_matches)
        if clip_author and clip_author in _book_author_keys(book)
    ]
    author_matches = _unique_books(author_matches)

    if len(author_matches) == 1:
        confidence = (
            "known_kindle_title_alias"
            if author_matches[0] in alias_matches
            else "normalized_title_author"
        )
        return _book_match(author_matches[0], confidence=confidence)
    if len(author_matches) > 1:
        return KindleClippingMatch(
            state="ambiguous",
            confidence="normalized_title_author",
            note="Ambiguous title and author",
        )
    title_matches = _unique_books(title_matches)
    if len(title_matches) > 1:
        return KindleClippingMatch(
            state="ambiguous",
            confidence="normalized_title",
            note="Ambiguous title",
        )
    if len(title_matches) == 1 and not clip_author:
        return KindleClippingMatch(
            state="needs_review",
            confidence="normalized_title",
            book_id=str(getattr(title_matches[0], "id", "") or ""),
            dragon_book_id=str(getattr(title_matches[0], "dragon_book_id", "") or ""),
            book_title=str(getattr(title_matches[0], "title", "") or ""),
            note="Unknown author",
        )
    if len(title_matches) == 1:
        return KindleClippingMatch(
            state="needs_review",
            confidence="normalized_title",
            book_id=str(getattr(title_matches[0], "id", "") or ""),
            dragon_book_id=str(getattr(title_matches[0], "dragon_book_id", "") or ""),
            book_title=str(getattr(title_matches[0], "title", "") or ""),
            note="Author mismatch",
        )
    return KindleClippingMatch(
        state="needs_review",
        confidence="missing_book_relation",
        note="Missing book relation",
    )


def parse_my_clippings(raw_text: str) -> KindleClippingsParseResult:
    clippings: list[KindleClipping] = []
    skipped = 0
    for block in ENTRY_DELIMITER.split(str(raw_text or "")):
        lines = [line.strip("\ufeff\r ") for line in block.splitlines()]
        lines = _trim_empty_edges(lines)
        if not lines:
            continue
        clipping = _parse_block(lines)
        if clipping is None:
            skipped += 1
        else:
            clippings.append(clipping)
    return KindleClippingsParseResult(clippings=clippings, skipped=skipped)


def queue_my_clippings(
    raw_text: str, state: KindleClippingsSyncState | Mapping | None = None
) -> KindleClippingsQueueResult:
    current = _sync_state(state)
    parsed = parse_my_clippings(raw_text)
    pending_hashes = {item.unique_hash for item in current.pending}
    seen_hashes: set[str] = set()
    queued: list[KindleClippingsOutboxItem] = []
    skipped_synced = 0
    skipped_pending = 0
    skipped_duplicate = 0

    for clipping in parsed.clippings:
        unique_hash = clipping.unique_hash
        if unique_hash in seen_hashes:
            skipped_duplicate += 1
            continue
        seen_hashes.add(unique_hash)
        if unique_hash in current.synced_hashes:
            skipped_synced += 1
            continue
        if unique_hash in pending_hashes:
            skipped_pending += 1
            continue
        item = KindleClippingsOutboxItem(
            unique_hash=unique_hash,
            payload=clipping.as_book_quote_payload(),
        )
        queued.append(item)
        pending_hashes.add(unique_hash)

    next_state = KindleClippingsSyncState(
        synced_hashes=current.synced_hashes,
        pending=(*current.pending, *queued),
    )
    return KindleClippingsQueueResult(
        state=next_state,
        queued=queued,
        parsed=len(parsed.clippings),
        skipped_malformed=parsed.skipped,
        skipped_synced=skipped_synced,
        skipped_pending=skipped_pending,
        skipped_duplicate=skipped_duplicate,
    )


def mark_clippings_uploaded(
    state: KindleClippingsSyncState | Mapping, uploaded_hashes: Iterable[str]
) -> KindleClippingsUploadResult:
    current = _sync_state(state)
    uploaded = {str(value) for value in uploaded_hashes}
    pending_hashes = {item.unique_hash for item in current.pending}
    matched = uploaded & pending_hashes
    next_state = KindleClippingsSyncState(
        synced_hashes=current.synced_hashes | matched,
        pending=tuple(item for item in current.pending if item.unique_hash not in matched),
    )
    return KindleClippingsUploadResult(
        state=next_state,
        uploaded=len(matched),
        missing=len(uploaded - pending_hashes),
    )


def mark_clippings_failed(
    state: KindleClippingsSyncState | Mapping, failures: Mapping[str, str]
) -> KindleClippingsFailureResult:
    current = _sync_state(state)
    failure_map = {str(key): str(value) for key, value in failures.items()}
    failed_at = utc_iso()
    failed = 0
    pending: list[KindleClippingsOutboxItem] = []
    for item in current.pending:
        error = failure_map.get(item.unique_hash)
        if error is None:
            pending.append(item)
            continue
        failed += 1
        pending.append(
            KindleClippingsOutboxItem(
                unique_hash=item.unique_hash,
                payload=item.payload,
                attempts=item.attempts + 1,
                last_error=error,
                last_error_at=failed_at,
            )
        )
    return KindleClippingsFailureResult(
        state=KindleClippingsSyncState(
            synced_hashes=current.synced_hashes,
            pending=tuple(pending),
        ),
        failed=failed,
        missing=len(set(failure_map) - {item.unique_hash for item in current.pending}),
    )


def assign_clipping_book(
    state: KindleClippingsSyncState | Mapping,
    *,
    unique_hash: str,
    book: object,
) -> KindleClippingsAssignResult:
    current = _sync_state(state)
    target_hash = str(unique_hash or "")
    pending: list[KindleClippingsOutboxItem] = []
    updated = False
    for item in current.pending:
        if item.unique_hash != target_hash:
            pending.append(item)
            continue
        updated = True
        pending.append(_assign_outbox_item_book(item, book))
    return KindleClippingsAssignResult(
        state=KindleClippingsSyncState(
            synced_hashes=current.synced_hashes,
            pending=tuple(pending),
        ),
        updated=updated,
    )


def remove_clipping_from_outbox(
    state: KindleClippingsSyncState | Mapping,
    *,
    unique_hash: str,
) -> KindleClippingsRemoveResult:
    current = _sync_state(state)
    target_hash = str(unique_hash or "")
    pending = tuple(item for item in current.pending if item.unique_hash != target_hash)
    return KindleClippingsRemoveResult(
        state=KindleClippingsSyncState(
            synced_hashes=current.synced_hashes,
            pending=pending,
        ),
        removed=len(pending) != len(current.pending),
    )


def remove_clippings_from_outbox(
    state: KindleClippingsSyncState | Mapping,
    *,
    unique_hashes: Iterable[str],
) -> KindleClippingsBulkRemoveResult:
    current = _sync_state(state)
    target_hashes = {str(value) for value in unique_hashes if str(value)}
    if not target_hashes:
        return KindleClippingsBulkRemoveResult(state=current, removed=0)
    pending = tuple(item for item in current.pending if item.unique_hash not in target_hashes)
    return KindleClippingsBulkRemoveResult(
        state=KindleClippingsSyncState(
            synced_hashes=current.synced_hashes,
            pending=pending,
        ),
        removed=len(current.pending) - len(pending),
    )


def reset_clipping_failures(
    state: KindleClippingsSyncState | Mapping,
    *,
    unique_hashes: Iterable[str],
) -> KindleClippingsResetFailuresResult:
    current = _sync_state(state)
    target_hashes = {str(value) for value in unique_hashes if str(value)}
    if not target_hashes:
        return KindleClippingsResetFailuresResult(state=current, reset=0)
    pending: list[KindleClippingsOutboxItem] = []
    reset = 0
    for item in current.pending:
        if item.unique_hash not in target_hashes or not item.last_error:
            pending.append(item)
            continue
        reset += 1
        pending.append(
            KindleClippingsOutboxItem(
                unique_hash=item.unique_hash,
                payload=item.payload,
                attempts=item.attempts,
                last_error="",
                last_error_at="",
            )
        )
    return KindleClippingsResetFailuresResult(
        state=KindleClippingsSyncState(
            synced_hashes=current.synced_hashes,
            pending=tuple(pending),
        ),
        reset=reset,
    )


def clipping_unique_hash(
    *, book_title: str, text: str, location: str, created_at: str
) -> str:
    ingredients = [
        normalize_title(book_title),
        _normalize_hash_text(text),
        _normalize_hash_text(location),
        _normalize_hash_text(created_at),
    ]
    return hashlib.sha256("\n".join(ingredients).encode("utf-8")).hexdigest()


def _parse_block(lines: list[str]) -> KindleClipping | None:
    if len(lines) < 2:
        return None
    title, author = _split_title_author(lines[0])
    match = META_PATTERN.match(lines[1])
    if not title or match is None:
        return None
    kind = match.group("kind").casefold()
    position = match.group("position")
    page = _match_value(PAGE_PATTERN, position)
    location = _match_value(LOCATION_PATTERN, position)
    created_at = " ".join(match.group("created_at").split())
    text = "\n".join(line for line in lines[2:] if line.strip()).strip()
    if kind in {"highlight", "note"} and not text:
        return None
    return KindleClipping(
        book_title=title,
        author=author,
        kind=kind,
        page=page,
        location=location,
        created_at=created_at,
        text=text,
        unique_hash=clipping_unique_hash(
            book_title=title,
            text=text,
            location=location,
            created_at=created_at,
        ),
    )


def _split_title_author(value: str) -> tuple[str, str]:
    text = " ".join(str(value or "").split())
    if text.endswith(")") and "(" in text:
        title, author = text.rsplit("(", 1)
        return title.strip(), author[:-1].strip()
    return text, ""


def _match_value(pattern: re.Pattern, value: str) -> str:
    match = pattern.search(str(value or ""))
    return match.group(1).strip() if match else ""


def _trim_empty_edges(lines: list[str]) -> list[str]:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _normalize_hash_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(text.split())


def _sync_state(state: KindleClippingsSyncState | Mapping | None) -> KindleClippingsSyncState:
    if isinstance(state, KindleClippingsSyncState):
        return state
    return KindleClippingsSyncState.from_dict(state)


def _outbox_item_from_dict(payload: Mapping) -> KindleClippingsOutboxItem:
    return KindleClippingsOutboxItem(
        unique_hash=str(payload.get("unique_hash") or ""),
        payload=dict(payload.get("payload") or {}),
        attempts=max(int(payload.get("attempts") or 0), 0),
        last_error=str(payload.get("last_error") or ""),
        last_error_at=str(payload.get("last_error_at") or ""),
    )


def _assign_outbox_item_book(
    item: KindleClippingsOutboxItem, book: object
) -> KindleClippingsOutboxItem:
    payload = dict(item.payload)
    payload.update(
        {
            "book_id": str(getattr(book, "id", "") or ""),
            "dragon_book_id": str(getattr(book, "dragon_book_id", "") or ""),
            "matched_book_title": str(getattr(book, "title", "") or ""),
            "match_source": "manual_local_review",
        }
    )
    return KindleClippingsOutboxItem(
        unique_hash=item.unique_hash,
        payload=payload,
        attempts=item.attempts,
        last_error=item.last_error,
        last_error_at=item.last_error_at,
    )


def _match_existing_relation(
    payload: Mapping, books: tuple[object, ...]
) -> KindleClippingMatch | None:
    book_id = str(payload.get("book_id") or payload.get("matched_book_id") or "")
    dragon_book_id = str(payload.get("dragon_book_id") or "")
    for book in books:
        if book_id and str(getattr(book, "id", "") or "") == book_id:
            return _book_match(book, confidence=_relation_confidence(payload))
        if dragon_book_id and str(getattr(book, "dragon_book_id", "") or "") == dragon_book_id:
            return _book_match(book, confidence=_relation_confidence(payload))

    relation_ids = _book_relation_ids(payload)
    relation_matches = [
        book
        for book in books
        if relation_ids & _book_notion_page_ids(book)
    ]
    relation_matches = _unique_books(relation_matches)
    if len(relation_matches) == 1:
        return _book_match(relation_matches[0], confidence="notion_book_relation")
    if len(relation_matches) > 1:
        return KindleClippingMatch(
            state="ambiguous",
            confidence="notion_book_relation",
            note="Ambiguous book relation",
        )

    if not book_id and not dragon_book_id and not relation_ids:
        return None
    return KindleClippingMatch(
        state="needs_review",
        confidence="missing_book_relation",
        note="Stored relation was not found locally",
    )


def _relation_confidence(payload: Mapping) -> str:
    if str(payload.get("match_source") or "") == "manual_local_review":
        return "manual_local_review"
    if payload.get("book_id") or payload.get("matched_book_id"):
        return "existing_relation"
    return "dragon_book_id"


def _book_relation_ids(payload: Mapping) -> set[str]:
    values = payload.get("book_relation_ids") or payload.get("book_relation_id") or ()
    if isinstance(values, str):
        values = values.split(",")
    if not isinstance(values, Iterable):
        values = (values,)
    return {
        _canonical_notion_id(value)
        for value in values
        if _canonical_notion_id(value)
    }


def _book_notion_page_ids(book: object) -> set[str]:
    external_ids = getattr(book, "external_ids", {}) or {}
    if not isinstance(external_ids, Mapping):
        return set()
    values = (
        external_ids.get("notion_page_id"),
        external_ids.get("notion_book_page_id"),
    )
    return {
        _canonical_notion_id(value)
        for value in values
        if _canonical_notion_id(value)
    }


def _canonical_notion_id(value: object) -> str:
    return str(value or "").strip().casefold().replace("-", "")


def _book_match(book: object, *, confidence: str) -> KindleClippingMatch:
    return KindleClippingMatch(
        state="matched",
        confidence=confidence,
        book_id=str(getattr(book, "id", "") or ""),
        dragon_book_id=str(getattr(book, "dragon_book_id", "") or ""),
        book_title=str(getattr(book, "title", "") or ""),
        note="Matched by " + confidence.replace("_", " "),
    )


def _book_title_keys(book: object) -> set[str]:
    values = [
        getattr(book, "title", ""),
        getattr(book, "original_title", ""),
        *[getattr(edition, "title", "") for edition in getattr(book, "editions", [])],
        *_book_alias_values(book),
    ]
    return {normalize_title(str(value)) for value in values if normalize_title(str(value))}


def _book_alias_keys(book: object) -> set[str]:
    return {
        normalize_title(str(value))
        for value in _book_alias_values(book)
        if normalize_title(str(value))
    }


def _book_alias_values(book: object) -> list[str]:
    metadata_state = getattr(book, "metadata_state", {}) or {}
    if not isinstance(metadata_state, Mapping):
        return []
    values = metadata_state.get("kindle_title_aliases", [])
    if isinstance(values, str):
        return [values]
    if isinstance(values, list):
        return [str(value) for value in values]
    return []


def _book_author_keys(book: object) -> set[str]:
    values = [
        *getattr(book, "authors", []),
        *getattr(book, "additional_authors", []),
    ]
    return {normalize_title(str(value)) for value in values if normalize_title(str(value))}


def _unique_books(books: Iterable[object]) -> list[object]:
    seen: set[str] = set()
    unique: list[object] = []
    for book in books:
        key = str(getattr(book, "id", "") or id(book))
        if key in seen:
            continue
        seen.add(key)
        unique.append(book)
    return unique
