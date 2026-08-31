from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from flask import current_app
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from app.books.book_quotes import BookQuotesSnapshotService
from app.books.clippings import project_clippings_outbox, workspace_aware_clippings_store
from app.books.matching import valid_isbn10, valid_isbn13
from app.books.models import (
    AudiobookAsset,
    AudiobookEdition,
    AvailabilityCandidate,
    Book,
    BookEdition,
    Quote,
    TextAsset,
)
from app.books.priorities import AUDIO_FORMATS, TEXT_FORMAT_PRIORITY, normalize_format
from app.extensions import db
from app.shared.time import utc_iso


class KnowledgeDiagnosticsService:
    @staticmethod
    def snapshot() -> dict[str, Any]:
        books = list(
            db.session.scalars(
                db.select(Book)
                .options(
                    selectinload(Book.editions).selectinload(BookEdition.text_assets),
                    selectinload(Book.audiobooks).selectinload(AudiobookEdition.assets),
                    selectinload(Book.availability_candidates),
                )
                .order_by(Book.updated_at.desc())
            )
        )
        text_assets = list(db.session.scalars(db.select(TextAsset)))
        audio_assets = list(db.session.scalars(db.select(AudiobookAsset)))
        candidates = list(db.session.scalars(db.select(AvailabilityCandidate)))
        clippings = _kindle_clippings_snapshot(books)
        book_quotes = BookQuotesSnapshotService.status(books=books)
        return {
            "summary": _summary(
                books, text_assets, audio_assets, candidates, clippings, book_quotes
            ),
            "text_formats": _format_counts(text_assets),
            "audio_formats": _audio_counts(audio_assets),
            "review": _review_state(books, candidates, clippings, book_quotes),
            "provider_boundaries": _provider_boundaries(book_quotes),
            "integrity": _integrity(books, text_assets, audio_assets),
            "queues": _queues(books, candidates, clippings, book_quotes),
            "book_quotes": book_quotes,
        }


def _count(model) -> int:
    return int(db.session.scalar(db.select(func.count()).select_from(model)) or 0)


def _summary(
    books: list[Book],
    text_assets: list[TextAsset],
    audio_assets: list[AudiobookAsset],
    candidates: list[AvailabilityCandidate],
    clippings: dict[str, int],
    book_quotes: dict[str, object],
) -> list[dict[str, object]]:
    metadata_counts = Counter(book.metadata_status for book in books)
    return [
        {"label": "Books", "value": len(books), "note": "canonical local works"},
        {
            "label": "Verified metadata",
            "value": metadata_counts.get("verified", 0),
            "note": "reviewed bibliographic state",
        },
        {"label": "Missing ISBN", "value": _missing_isbn_count(books), "note": "no ISBN stored"},
        {
            "label": "No ISBN",
            "value": metadata_counts.get("no_isbn", 0),
            "note": "explicitly marked as legitimate",
        },
        {
            "label": "Unmatched books",
            "value": _unmatched_book_count(books),
            "note": "no local text asset or candidate",
        },
        {
            "label": "Needs review",
            "value": _metadata_review_count(books),
            "note": "metadata inbox",
        },
        {
            "label": "Last metadata refresh",
            "value": _latest_metadata_refresh_label(books),
            "note": "most recent local metadata update",
        },
        {
            "label": "Last error",
            "value": clippings["last_error"],
            "note": clippings["last_error_note"],
        },
        {"label": "Editions", "value": _count(BookEdition), "note": "text editions"},
        {"label": "Text assets", "value": len(text_assets), "note": "KFX/AZW3/EPUB/PDF"},
        {"label": "PDF-only", "value": _pdf_only_count(books), "note": "final-priority text only"},
        {"label": "Audiobooks", "value": _count(AudiobookEdition), "note": "parallel editions"},
        {"label": "Audio assets", "value": len(audio_assets), "note": "M4B/MP3/AAC"},
        {"label": "Candidates", "value": len(candidates), "note": "review-only availability"},
        {
            "label": "Local storage",
            "value": _local_storage_label(text_assets, audio_assets),
            "note": "registered local asset inventory",
        },
        {
            "label": "Unmatched highlights",
            "value": clippings["unmatched_highlights"],
            "note": "local Kindle outbox",
        },
        {
            "label": "Book Quotes rows",
            "value": book_quotes["item_count"],
            "note": "cached canonical highlights",
        },
        {
            "label": "Last Book Quotes refresh",
            "value": book_quotes["refreshed_at"] or "Never",
            "note": "explicit local snapshot",
        },
        {"label": "Quotes", "value": _count(Quote), "note": "local quote cache"},
    ]


def _format_counts(text_assets: list[TextAsset]) -> list[dict[str, object]]:
    counts = Counter(normalize_format(asset.format) for asset in text_assets)
    return [
        {
            "format": name,
            "count": counts.get(name, 0),
            "priority": index,
            "available": counts.get(name, 0) > 0,
        }
        for index, name in enumerate(TEXT_FORMAT_PRIORITY, start=1)
    ]


def _audio_counts(audio_assets: list[AudiobookAsset]) -> list[dict[str, object]]:
    counts = Counter(normalize_format(asset.format) for asset in audio_assets)
    return [
        {"format": name, "count": counts.get(name, 0), "available": counts.get(name, 0) > 0}
        for name in AUDIO_FORMATS
    ]


def _review_state(
    books: list[Book],
    candidates: list[AvailabilityCandidate],
    clippings: dict[str, int],
    book_quotes: dict[str, object],
) -> dict[str, object]:
    metadata_needs_review = [
        book
        for book in books
        if _needs_metadata_review(book)
    ]
    no_text_assets = [book for book in books if not _book_text_assets(book)]
    no_audiobooks = [book for book in books if not book.audiobooks]
    candidate_counts = Counter(candidate.review_state for candidate in candidates)
    return {
        "unmatched_books": _unmatched_book_count(books),
        "metadata_needs_review": len(metadata_needs_review),
        "no_text_assets": len(no_text_assets),
        "no_audiobooks": len(no_audiobooks),
        "candidates_review_required": candidate_counts.get("review_required", 0),
        "candidates_confirmed": candidate_counts.get("confirmed", 0),
        "candidates_rejected": candidate_counts.get("rejected", 0),
        "kindle_pending": clippings["pending"],
        "kindle_matched": clippings["matched"],
        "kindle_ambiguous": clippings["ambiguous"],
        "kindle_needs_review": clippings["needs_review"],
        "kindle_failed": clippings["failed"],
        "unmatched_highlights": clippings["unmatched_highlights"],
        "book_quotes_matched": book_quotes["matched"],
        "book_quotes_ambiguous": book_quotes["ambiguous"],
        "book_quotes_needs_review": book_quotes["needs_review"],
    }


def _provider_boundaries(book_quotes: dict[str, object]) -> list[dict[str, str]]:
    book_quotes_state = "Refreshed"
    book_quotes_note = (
        f"{book_quotes['item_count']} cached row(s) from "
        f"{book_quotes['refreshed_at']}."
    )
    if book_quotes["last_error"]:
        book_quotes_state = "Needs review"
        checked_suffix = (
            f" · checked {book_quotes['last_checked_at']}"
            if book_quotes["last_checked_at"]
            else ""
        )
        book_quotes_note = (
            f"{book_quotes['last_error']}"
            f"{checked_suffix}"
        )
    elif not book_quotes["refreshed_at"]:
        if book_quotes["configured"]:
            book_quotes_state = "Configured"
            book_quotes_note = "Ready for an explicit local refresh."
        else:
            book_quotes_state = "Not configured"
            book_quotes_note = (
                "Configure the dedicated local Book Quotes target before refresh."
            )
    return [
        {
            "label": "Notion Knowledge",
            "state": "Audit required",
            "note": "Personal library source of truth is not inspected in this runtime yet.",
        },
        {
            "label": "Book Quotes",
            "state": book_quotes_state,
            "note": book_quotes_note,
        },
        {
            "label": "Open Library / Google Books",
            "state": "Explicit only",
            "note": "Metadata lookups run only from POST preview actions.",
        },
        {
            "label": "Telegram / Jackett",
            "state": "Review only",
            "note": "Provider results can be candidates, never automatic assets.",
        },
        {
            "label": "PythonAnywhere",
            "state": "Removed",
            "note": "Knowledge runs local-only in this roadmap.",
        },
    ]


def _integrity(
    books: list[Book], text_assets: list[TextAsset], audio_assets: list[AudiobookAsset]
) -> list[dict[str, object]]:
    dragon_ids = [book.dragon_book_id for book in books if book.dragon_book_id]
    duplicate_dragon_ids = sum(count - 1 for count in Counter(dragon_ids).values() if count > 1)
    missing_dragon_ids = sum(1 for book in books if not book.dragon_book_id)
    text_duplicate_hashes = _duplicate_hash_count([asset.file_hash for asset in text_assets])
    audio_duplicate_hashes = _duplicate_hash_count([asset.file_hash for asset in audio_assets])
    malformed_isbns = _malformed_isbn_count(books)
    duplicate_candidates = _duplicate_candidate_count(books)
    return [
        _signal("DragonBookID", missing_dragon_ids + duplicate_dragon_ids, "Stable identity"),
        _signal("ISBN format", malformed_isbns, "ISBN-10/13 checksum validation"),
        _signal("Authors", _missing_author_count(books), "Canonical author coverage"),
        _signal(
            "Edition language",
            _missing_language_count(books),
            "Primary edition language coverage",
        ),
        _signal("Publisher", _missing_publisher_count(books), "Primary edition publisher coverage"),
        _signal("Cover", _missing_cover_count(books), "Book or edition cover coverage"),
        _signal("Duplicate candidates", duplicate_candidates, "Availability candidate dedupe"),
        _signal("Text asset hashes", text_duplicate_hashes, "Duplicate prevention"),
        _signal("Audio asset hashes", audio_duplicate_hashes, "Duplicate prevention"),
        _signal(
            "Provider automation",
            0,
            "No automatic acquisition routes are enabled for Knowledge.",
        ),
    ]


def _queues(
    books: list[Book],
    candidates: list[AvailabilityCandidate],
    clippings: dict[str, object],
    book_quotes: dict[str, object],
) -> dict[str, list[dict[str, object]]]:
    metadata = [
        {
            "title": book.title,
            "detail_url_id": book.id,
            "state": book.metadata_status,
            "note": book.metadata_confidence or "unscored",
        }
        for book in books
        if _needs_metadata_review(book)
    ][:8]
    assets = [
        {
            "title": book.title,
            "detail_url_id": book.id,
            "state": "missing_text_asset",
            "note": "No registered text asset",
        }
        for book in books
        if not _book_text_assets(book)
    ][:8]
    unmatched_books = [
        {
            "title": book.title,
            "detail_url_id": book.id,
            "state": "unmatched_book",
            "note": "No registered text asset or availability candidate",
        }
        for book in books
        if _is_unmatched_book(book)
    ][:8]
    availability = [
        {
            "title": candidate.title,
            "detail_url_id": candidate.book_id,
            "state": candidate.review_state,
            "note": f"{candidate.provider} · {candidate.format_guess or 'unknown format'}",
        }
        for candidate in candidates
        if candidate.review_state == "review_required"
    ][:8]
    return {
        "metadata": metadata,
        "assets": assets,
        "unmatched_books": unmatched_books,
        "availability": availability,
        "kindle": list(clippings.get("queue", [])),
        "book_quotes": list(book_quotes.get("queue", [])),
    }


def _kindle_clippings_snapshot(books: list[Book]) -> dict[str, object]:
    state_path = Path(current_app.instance_path) / "knowledge" / "kindle_clippings_sync.json"
    projection = project_clippings_outbox(workspace_aware_clippings_store(state_path).load(), books)
    counts = Counter(item.match.state for item in projection)
    queue = [
        {
            "title": str(item.item.payload.get("book_title") or "Kindle clipping"),
            "url": _kindle_queue_url(item),
            "state": item.match.state,
            "note": _kindle_queue_note(item),
        }
        for item in projection
        if item.match.state != "matched"
    ][:8]
    unmatched_highlights = sum(
        1
        for item in projection
        if _is_highlight_like(item.item.payload) and item.match.state != "matched"
    )
    return {
        "pending": len(projection),
        "matched": counts.get("matched", 0),
        "ambiguous": counts.get("ambiguous", 0),
        "needs_review": counts.get("needs_review", 0),
        "failed": sum(1 for item in projection if item.item.last_error),
        "unmatched_highlights": unmatched_highlights,
        "last_error": _last_outbox_error_label(projection),
        "last_error_note": _last_outbox_error_note(projection),
        "queue": queue,
    }


def _is_highlight_like(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    kind = str(payload.get("kind") or "highlight").strip().casefold()
    return kind != "bookmark"


def _kindle_queue_note(item) -> str:
    kind = str(item.item.payload.get("kind") or "highlight").strip().casefold() or "highlight"
    source = kind.title()
    detail = item.match.note or item.match.confidence.replace("_", " ")
    return f"{source} · {detail}"


def _kindle_queue_url(item) -> str:
    if item.item.last_error:
        return "/settings/knowledge/kindle-clippings?state=failed"
    if item.match.state == "ambiguous":
        return "/settings/knowledge/kindle-clippings?state=ambiguous"
    if item.match.state == "needs_review":
        return "/settings/knowledge/kindle-clippings?state=review"
    return "/settings/knowledge/kindle-clippings"


def _last_outbox_error_label(projection: tuple[object, ...]) -> str:
    item = _last_outbox_error_item(projection)
    if item is None:
        return "Never"
    return item.item.last_error or "Never"


def _last_outbox_error_note(projection: tuple[object, ...]) -> str:
    item = _last_outbox_error_item(projection)
    if item is None:
        return "local Kindle outbox"
    if item.item.last_error_at:
        return f"local Kindle outbox · {item.item.last_error_at}"
    return "local Kindle outbox"


def _last_outbox_error_item(projection: tuple[object, ...]):
    errored = [item for item in projection if item.item.last_error]
    if not errored:
        return None
    return max(errored, key=lambda item: item.item.last_error_at or "")


def _latest_metadata_refresh_label(books: list[Book]) -> str:
    stamps = [book.last_metadata_refresh_at for book in books if book.last_metadata_refresh_at]
    if not stamps:
        return "Never"
    latest = max(stamps)
    return utc_iso(latest)


def _local_storage_label(
    text_assets: list[TextAsset], audio_assets: list[AudiobookAsset]
) -> str:
    total = sum(
        max(int(asset.file_size or 0), 0)
        for asset in [*text_assets, *audio_assets]
        if asset.source_type == "local" and asset.availability_status != "rejected"
    )
    return _file_size_label(total)


def _file_size_label(size: int) -> str:
    value = max(int(size or 0), 0)
    units = ["B", "KB", "MB", "GB"]
    amount = float(value)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    if unit == "B":
        return f"{value} B"
    return f"{amount:.1f} {unit}"


def _book_text_assets(book: Book) -> list[TextAsset]:
    return [asset for edition in book.editions for asset in edition.text_assets]


def _unmatched_book_count(books: list[Book]) -> int:
    return sum(1 for book in books if _is_unmatched_book(book))


def _is_unmatched_book(book: Book) -> bool:
    if _book_text_assets(book):
        return False
    return not any(
        candidate.review_state in {"review_required", "confirmed"}
        for candidate in book.availability_candidates
    )


def _pdf_only_count(books: list[Book]) -> int:
    return sum(1 for book in books if _book_text_format_set(book) == {"PDF"})


def _book_text_format_set(book: Book) -> set[str]:
    return {
        normalize_format(asset.format)
        for asset in _book_text_assets(book)
        if asset.availability_status != "rejected"
    } & set(TEXT_FORMAT_PRIORITY)


def _metadata_review_count(books: list[Book]) -> int:
    return sum(1 for book in books if _needs_metadata_review(book))


def _needs_metadata_review(book: Book) -> bool:
    return book.metadata_status in {"missing", "candidate_found", "needs_review", "error"}


def _missing_isbn_count(books: list[Book]) -> int:
    return sum(1 for book in books if book.metadata_status != "no_isbn" and not _has_isbn(book))


def _has_isbn(book: Book) -> bool:
    return (
        _has_text(book.isbn_10)
        or _has_text(book.isbn_13)
        or any(
            _has_text(edition.isbn_10) or _has_text(edition.isbn_13)
            for edition in book.editions
        )
    )


def _duplicate_hash_count(values: list[str]) -> int:
    hashes = [value for value in values if value]
    return sum(count - 1 for count in Counter(hashes).values() if count > 1)


def _malformed_isbn_count(books: list[Book]) -> int:
    issue_count = 0
    for book in books:
        issue_count += _isbn_issue_count(book.isbn_10, kind="isbn_10")
        issue_count += _isbn_issue_count(book.isbn_13, kind="isbn_13")
        for edition in book.editions:
            issue_count += _isbn_issue_count(edition.isbn_10, kind="isbn_10")
            issue_count += _isbn_issue_count(edition.isbn_13, kind="isbn_13")
    return issue_count


def _missing_author_count(books: list[Book]) -> int:
    return sum(1 for book in books if not _has_json_text(book.authors))


def _missing_language_count(books: list[Book]) -> int:
    return sum(1 for book in books if not _has_language(book))


def _missing_publisher_count(books: list[Book]) -> int:
    return sum(1 for book in books if not _has_publisher(book))


def _missing_cover_count(books: list[Book]) -> int:
    return sum(1 for book in books if not _has_cover(book))


def _duplicate_candidate_count(books: list[Book]) -> int:
    keys = []
    for book in books:
        keys.extend(_candidate_key(book, candidate) for candidate in book.availability_candidates)
    return sum(count - 1 for count in Counter(keys).values() if count > 1)


def _candidate_key(book: Book, candidate: AvailabilityCandidate) -> tuple[str, str, str, str, str]:
    title_key = " ".join(str(candidate.title or "").split()).casefold()
    return (
        book.id,
        str(candidate.provider or "").strip().casefold(),
        title_key,
        normalize_format(candidate.format_guess),
        str(candidate.source_reference or "").strip(),
    )


def _has_language(book: Book) -> bool:
    return (
        _has_text(book.edition_language)
        or any(_has_text(edition.language) for edition in book.editions)
        or any(_has_text(audiobook.language) for audiobook in book.audiobooks)
    )


def _has_publisher(book: Book) -> bool:
    return (
        _has_text(book.publisher)
        or any(_has_text(edition.publisher) for edition in book.editions)
        or any(_has_text(audiobook.publisher) for audiobook in book.audiobooks)
    )


def _has_cover(book: Book) -> bool:
    return (
        _has_text(book.cover_url)
        or any(_has_text(edition.cover_url) for edition in book.editions)
        or any(_has_text(audiobook.cover_url) for audiobook in book.audiobooks)
    )


def _has_json_text(values: object) -> bool:
    return isinstance(values, list) and any(_has_text(value) for value in values)


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _isbn_issue_count(value: str, *, kind: str) -> int:
    if not value:
        return 0
    if kind == "isbn_10":
        return 0 if valid_isbn10(value) else 1
    return 0 if valid_isbn13(value) else 1


def _signal(label: str, issue_count: int, note: str) -> dict[str, object]:
    return {
        "label": label,
        "issue_count": issue_count,
        "state": "clear" if issue_count == 0 else "attention",
        "note": note,
    }
