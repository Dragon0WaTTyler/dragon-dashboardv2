from __future__ import annotations

from app.books.kindle import BookKindleExportService
from app.books.matching import normalize_title
from app.books.models import (
    AudiobookAsset,
    AudiobookEdition,
    Book,
    BookEdition,
    Quote,
    TextAsset,
)
from app.books.primary_editions import effective_book_value
from app.books.priorities import TEXT_FORMAT_PRIORITY, preferred_text_format, text_format_slots
from app.books.runtime import listening_progress
from app.books.statuses import ALL_BOOK_STATUSES, normalize_book_status
from app.extensions import db
from app.history.services import HistoryService
from app.shared.text import text_direction
from app.shared.time import utc_iso

BOOK_STATUSES = ALL_BOOK_STATUSES


def _text_assets(book: Book) -> list[TextAsset]:
    return [asset for edition in book.editions for asset in edition.text_assets]


def _asset_formats(book: Book) -> list[str]:
    formats = [
        asset.format for asset in _text_assets(book) if asset.availability_status != "rejected"
    ]
    metadata_state = book.metadata_state if isinstance(book.metadata_state, dict) else {}
    legacy_formats = metadata_state.get("formats_available", [])
    if isinstance(legacy_formats, list):
        formats.extend(str(value) for value in legacy_formats)
    return formats


def _edition_item(edition: BookEdition) -> dict:
    return {
        "id": edition.id,
        "title": edition.title,
        "subtitle": edition.subtitle,
        "language": edition.language,
        "translator": edition.translator,
        "publisher": edition.publisher,
        "publication_year": edition.publication_year,
        "page_count": edition.page_count,
        "isbn_10": edition.isbn_10,
        "isbn_13": edition.isbn_13,
        "verification_status": edition.verification_status,
        "primary": edition.primary,
        "asset_count": len(edition.text_assets),
    }


def _asset_item(asset: TextAsset) -> dict:
    normalized_format = asset.format.upper()
    return {
        "id": asset.id,
        "format": normalized_format,
        "source_type": asset.source_type,
        "filename": asset.filename,
        "file_size": asset.file_size,
        "file_size_label": _file_size_label(asset.file_size),
        "availability_status": asset.availability_status,
        "verification_status": asset.verification_status,
        "preferred_for_kindle": asset.preferred_for_kindle,
        "runtime_label": _text_runtime_label(normalized_format),
        "opens_in_browser": normalized_format == "PDF",
        "opens_reader": normalized_format == "EPUB",
    }


def _audio_asset_item(asset: AudiobookAsset) -> dict:
    return {
        "id": asset.id,
        "format": asset.format.upper(),
        "source_type": asset.source_type,
        "filename": asset.filename,
        "file_size": asset.file_size,
        "file_size_label": _file_size_label(asset.file_size),
        "availability_status": asset.availability_status,
    }


def _audiobook_item(audiobook: AudiobookEdition, progress: dict | None = None) -> dict:
    progress = progress or {}
    return {
        "id": audiobook.id,
        "title": audiobook.title,
        "language": audiobook.language,
        "narrator": audiobook.narrator,
        "publisher": audiobook.publisher,
        "release_year": audiobook.release_year,
        "duration_seconds": audiobook.duration_seconds,
        "duration_label": _duration_label(audiobook.duration_seconds),
        "progress": {
            "position_seconds": int(progress.get("position_seconds") or 0),
            "position_label": _duration_label(progress.get("position_seconds") or 0),
            "duration_seconds": int(
                progress.get("duration_seconds") or audiobook.duration_seconds or 0
            ),
            "current_chapter": int(progress.get("current_chapter") or 0),
            "playback_speed": float(progress.get("playback_speed") or 1),
            "completed": bool(progress.get("completed")),
            "updated_at": progress.get("updated_at") or "",
        },
        "chapter_count": audiobook.chapter_count,
        "abridgement_type": audiobook.abridgement_type,
        "production_type": audiobook.production_type,
        "verification_status": audiobook.verification_status,
        "review_tone": "success"
        if audiobook.verification_status == "verified"
        else "warning"
        if audiobook.verification_status == "needs_review"
        else "",
        "asset_count": len(audiobook.assets),
        "assets": [_audio_asset_item(asset) for asset in audiobook.assets],
    }


def book_item(book: Book, *, external_highlight_count: int = 0) -> dict:
    metadata_state = book.metadata_state if isinstance(book.metadata_state, dict) else {}
    effective_page_count = int(effective_book_value(book, "page_count") or 0)
    if not effective_page_count:
        effective_page_count = _metadata_int(metadata_state, "notion_page_count")
    display_current_page = int(
        book.current_page or _metadata_int(metadata_state, "notion_current_page") or 0
    )
    percent = (
        round(display_current_page / effective_page_count * 100)
        if effective_page_count and display_current_page
        else _metadata_int(metadata_state, "notion_progress_percent") or 0
    )
    direction_source = " ".join([book.title, *book.authors])
    formats = _asset_formats(book)
    preferred = preferred_text_format(formats)
    canonical_status = normalize_book_status(book.status)
    return {
        "id": book.id,
        "dragon_book_id": book.dragon_book_id,
        "title": book.title,
        "original_title": book.original_title,
        "authors": book.authors,
        "cover_url": effective_book_value(book, "cover_url"),
        "status": canonical_status,
        "current_page": display_current_page,
        "page_count": effective_page_count,
        "progress_percent": min(percent, 100),
        "personal_score": book.personal_score,
        "favorite": book.favorite,
        "metadata_status": book.metadata_status,
        "metadata_confidence": book.metadata_confidence,
        "preferred_format": preferred,
        "other_formats": [
            slot["format"]
            for slot in text_format_slots(formats)
            if slot["available"] and slot["format"] != preferred
        ],
        "format_slots": text_format_slots(formats),
        "has_audiobook": bool(book.audiobooks),
        "audiobook_count": len(book.audiobooks),
        "external_highlight_count": max(int(external_highlight_count or 0), 0),
        "has_external_highlights": max(int(external_highlight_count or 0), 0) > 0,
        "needs_review": book.metadata_status
        in {"missing", "candidate_found", "needs_review", "error"}
        or any(
            candidate.review_state == "review_required"
            for candidate in book.availability_candidates
        ),
        "direction": text_direction(direction_source),
    }


def book_detail(
    book: Book,
    *,
    external_highlights: list[dict] | None = None,
    book_quotes_status: dict | None = None,
) -> dict:
    assets = _text_assets(book)
    return {
        **book_item(book),
        "description": book.description,
        "edition_language": effective_book_value(book, "edition_language"),
        "original_language": book.original_language,
        "translator": effective_book_value(book, "translator"),
        "publisher": effective_book_value(book, "publisher"),
        "published_year": effective_book_value(book, "published_year"),
        "isbn_10": effective_book_value(book, "isbn_10"),
        "isbn_13": effective_book_value(book, "isbn_13"),
        "series_name": book.series_name,
        "series_position": book.series_position,
        "subjects": book.subjects,
        "genres": book.genres,
        "collections": book.collections,
        "personal_tags": book.personal_tags,
        "personal_notes": book.personal_notes,
        "source": book.source,
        "editions": [_edition_item(edition) for edition in book.editions],
        "text_assets": sorted(
            [_asset_item(asset) for asset in assets],
            key=lambda item: TEXT_FORMAT_PRIORITY.index(item["format"])
            if item["format"] in TEXT_FORMAT_PRIORITY
            else len(TEXT_FORMAT_PRIORITY),
        ),
        "kindle_export_ready": BookKindleExportService.has_transfer_assets(book),
        "audiobooks": [
            _audiobook_item(audiobook, listening_progress(book, audiobook.id))
            for audiobook in book.audiobooks
        ],
        "availability_candidates": [
            {
                "id": candidate.id,
                "provider": candidate.provider,
                "title": candidate.title,
                "format_guess": candidate.format_guess,
                "language_guess": candidate.language_guess,
                "source_reference": candidate.source_reference,
                "size_bytes": candidate.size_bytes,
                "size_label": _file_size_label(candidate.size_bytes),
                "match_confidence": candidate.match_confidence,
                "review_state": candidate.review_state,
                "review_tone": "success"
                if candidate.review_state == "confirmed"
                else "warning"
                if candidate.review_state == "review_required"
                else "",
            }
            for candidate in book.availability_candidates
        ],
        "quotes": [
            {
                "id": quote.id,
                "text": quote.text,
                "page": quote.page,
                "note": quote.note,
                "direction": text_direction(quote.text),
            }
            for quote in book.quotes
        ],
        "external_highlights": external_highlights or [],
        "book_quotes_status": book_quotes_status or {},
        "metadata_state": book.metadata_state,
        "kindle_title_aliases": _kindle_title_aliases(book),
        "metadata_preview": (book.metadata_state or {}).get("metadata_preview"),
        "local_text_asset_preview": (book.metadata_state or {}).get(
            "local_text_asset_preview"
        ),
        "local_audio_asset_preview": (book.metadata_state or {}).get(
            "local_audio_asset_preview"
        ),
    }


def quotes_view(
    books: list[Book] | None = None,
    *,
    query: str = "",
    book_id: str = "",
) -> dict[str, object]:
    local_books = books if books is not None else list(Book.query.all())
    rows = sorted(
        [
            _quote_row(book, quote)
            for book in local_books
            for quote in book.quotes
            if str(quote.text or "").strip()
        ],
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("id") or ""),
        ),
        reverse=True,
    )
    query = " ".join(str(query or "").split())
    selected_book_id = str(book_id or "").strip()
    filtered = [
        row
        for row in rows
        if (not selected_book_id or row["book_id"] == selected_book_id)
        and _matches_quote_query(row, query=query)
    ]
    return {
        "count": len(rows),
        "filtered_count": len(filtered),
        "book_count": len({row["book_id"] for row in rows if row["book_id"]}),
        "query": query,
        "book_id": selected_book_id,
        "rows": filtered,
        "book_options": [
            {
                "id": book.id,
                "title": book.title,
                "authors": ", ".join(book.authors),
                "count": sum(1 for row in rows if row["book_id"] == book.id),
            }
            for book in sorted(
                [book for book in local_books if book.quotes],
                key=lambda item: str(item.title or "").casefold(),
            )
        ],
    }


def _quote_row(book: Book, quote: Quote) -> dict[str, object]:
    created_at = quote.created_at.isoformat() if quote.created_at else ""
    return {
        "id": quote.id,
        "book_id": book.id,
        "book_title": book.title,
        "book_authors": ", ".join(book.authors) or "Unknown author",
        "text": quote.text,
        "note": quote.note,
        "page": quote.page,
        "created_at": created_at,
        "direction": text_direction(quote.text),
    }


def _matches_quote_query(row: dict[str, object], *, query: str) -> bool:
    phrase = str(query or "").strip().casefold()
    if not phrase:
        return True
    haystacks = [
        row.get("text"),
        row.get("note"),
        row.get("book_title"),
        row.get("book_authors"),
        row.get("page"),
    ]
    return any(phrase in str(value or "").casefold() for value in haystacks)


class BookService:
    @staticmethod
    def current_books(*, limit: int | None = None) -> list[dict]:
        from app.books.repositories import BookRepository

        books = BookRepository.list(status="reading")
        if limit is not None:
            books = books[: max(int(limit), 0)]
        return [book_item(book) for book in books]

    @staticmethod
    def current_book() -> dict | None:
        books = BookService.current_books(limit=1)
        return books[0] if books else None

    @staticmethod
    def save_progress(book: Book, *, status: str, current_page: int) -> None:
        if status not in BOOK_STATUSES:
            raise ValueError("Unknown book status.")
        if current_page < 0 or (book.page_count and current_page > book.page_count):
            raise ValueError("Page progress is outside the book range.")
        canonical_status = normalize_book_status(status)
        book.status = canonical_status
        book.current_page = current_page
        book.history = [*book.history, {"event": "progress", "at": utc_iso(), "page": current_page}]
        HistoryService.record(
            domain="books",
            entity_type="book",
            entity_id=book.id,
            event_type="progress",
            label=f"{book.title}: page {current_page}",
            metadata={"status": canonical_status, "current_page": current_page},
        )
        db.session.commit()

    @staticmethod
    def add_quote(book: Book, *, text: str, page: int | None, note: str = "") -> Quote:
        normalized = " ".join(text.split())
        if not normalized:
            raise ValueError("Quote text is required.")
        if page is not None and (page < 1 or (book.page_count and page > book.page_count)):
            raise ValueError("Quote page is outside the book range.")
        quote = Quote(book=book, text=normalized, page=page, note=note.strip())
        db.session.add(quote)
        HistoryService.record(
            domain="books",
            entity_type="book",
            entity_id=book.id,
            event_type="quote_added",
            label=f"Added a quote from {book.title}",
        )
        db.session.commit()
        return quote

    @staticmethod
    def add_kindle_title_alias(book: Book, *, alias: str) -> None:
        value = " ".join(str(alias or "").split())
        if not value:
            raise ValueError("Kindle title alias is required.")
        if len(value) > 500:
            raise ValueError("Kindle title alias is too long.")
        aliases = _kindle_title_aliases(book)
        normalized_aliases = {normalize_title(item) for item in aliases}
        if normalize_title(value) in normalized_aliases:
            raise ValueError("Kindle title alias already exists.")
        book.metadata_state = {
            **(book.metadata_state or {}),
            "kindle_title_aliases": [*aliases, value],
        }
        HistoryService.record(
            domain="books",
            entity_type="book",
            entity_id=book.id,
            event_type="kindle_alias_added",
            label=f"Added a Kindle title alias for {book.title}",
        )
        db.session.commit()

    @staticmethod
    def remove_kindle_title_alias(book: Book, *, alias: str) -> None:
        normalized = normalize_title(str(alias or ""))
        aliases = _kindle_title_aliases(book)
        remaining = [item for item in aliases if normalize_title(item) != normalized]
        if len(remaining) == len(aliases):
            raise ValueError("Kindle title alias was not found.")
        book.metadata_state = {
            **(book.metadata_state or {}),
            "kindle_title_aliases": remaining,
        }
        HistoryService.record(
            domain="books",
            entity_type="book",
            entity_id=book.id,
            event_type="kindle_alias_removed",
            label=f"Removed a Kindle title alias for {book.title}",
        )
        db.session.commit()


def _metadata_int(metadata_state: dict, key: str) -> int:
    try:
        value = metadata_state.get(key)
        return int(value) if value not in (None, "") else 0
    except (TypeError, ValueError):
        return 0


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


def _kindle_title_aliases(book: Book) -> list[str]:
    metadata_state = book.metadata_state or {}
    aliases = metadata_state.get("kindle_title_aliases", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    if not isinstance(aliases, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in aliases:
        alias = " ".join(str(value or "").split())
        normalized = normalize_title(alias)
        if not alias or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(alias)
    return cleaned


def _duration_label(seconds: int) -> str:
    value = max(int(seconds or 0), 0)
    if value <= 0:
        return ""
    hours, remainder = divmod(value, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def _text_runtime_label(text_format: str) -> str:
    return {
        "PDF": "Open PDF",
        "EPUB": "Read EPUB",
        "AZW3": "Kindle file",
        "KFX": "Kindle file",
    }.get(text_format.upper(), "Download")
