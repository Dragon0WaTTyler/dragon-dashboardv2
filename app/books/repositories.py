from __future__ import annotations

from sqlalchemy.orm import selectinload

from app.books.matching import normalize_title
from app.books.notion_sync import BookNotionSyncService
from app.books.models import AudiobookEdition, Book, BookEdition, TextAsset
from app.books.priorities import TEXT_FORMAT_PRIORITY, normalize_format, sort_text_formats
from app.books.statuses import status_filter_values
from app.extensions import db


class BookRepository:
    @staticmethod
    def get(book_id: str) -> Book | None:
        BookNotionSyncService.ensure_synced()
        return db.session.scalar(
            db.select(Book)
            .options(
                selectinload(Book.quotes),
                selectinload(Book.editions).selectinload(BookEdition.text_assets),
                selectinload(Book.audiobooks).selectinload(AudiobookEdition.assets),
                selectinload(Book.availability_candidates),
            )
            .where((Book.id == book_id) | (Book.dragon_book_id == book_id))
        )

    @staticmethod
    def list(
        *,
        q: str = "",
        status: str = "",
        format: str = "",
        language: str = "",
        metadata: str = "",
        audiobook: str = "",
        author: str = "",
        translator: str = "",
        highlights: str = "",
        quotes: str = "",
        notes: str = "",
        collection: str = "",
        review: str = "",
    ) -> list[Book]:
        conditions = []
        query = q.strip()
        if status:
            values = status_filter_values(status)
            if values:
                conditions.append(Book.status.in_(values))

        def filtered_books() -> list[Book]:
            books = list(
                db.session.scalars(
                    _book_select()
                    .where(*conditions)
                    .order_by(Book.updated_at.desc())
                )
            )
            highlight_texts_by_book: dict[str, tuple[str, ...]] = {}
            highlight_counts_by_book: dict[str, int] = {}
            if query or str(highlights or "").strip():
                highlight_texts_by_book, highlight_counts_by_book = _book_highlight_cache(books)
            return [
                book
                for book in books
                if _matches_query(
                    book,
                    query,
                    highlight_texts=highlight_texts_by_book.get(book.id, ()),
                )
                and _matches_format(book, format)
                and _matches_language(book, language)
                and _matches_metadata(book, metadata)
                and _matches_audiobook(book, audiobook)
                and _matches_author(book, author)
                and _matches_translator(book, translator)
                and _matches_highlights(
                    book,
                    highlights,
                    highlight_count=highlight_counts_by_book.get(book.id, 0),
                )
                and _matches_quotes(book, quotes)
                and _matches_notes(book, notes)
                and _matches_collection(book, collection)
                and _matches_review(book, review)
            ]

        sync_result = BookNotionSyncService.ensure_synced()
        results = filtered_books()
        if query and not results and sync_result.configured and not sync_result.refreshed:
            BookNotionSyncService.ensure_synced(force=True)
            results = filtered_books()
        return results


def _matches_query(
    book: Book,
    query: str,
    *,
    highlight_texts: tuple[str, ...] = (),
) -> bool:
    if not query:
        return True
    needle = normalize_title(query)
    if not needle:
        requested_format = normalize_format(query)
        if requested_format in TEXT_FORMAT_PRIORITY:
            return requested_format in _book_formats(book) or any(
                candidate.format_guess == requested_format
                for candidate in book.availability_candidates
            )
        return True
    haystack = normalize_title(
        " ".join(
            [
                book.title,
                book.original_title,
                *book.authors,
                *book.additional_authors,
                book.description,
                book.edition_language,
                book.original_language,
                book.translator,
                book.publisher,
                book.isbn_10,
                book.isbn_13,
                book.series_name,
                book.dragon_book_id,
                *book.subjects,
                *book.genres,
                *book.collections,
                *book.personal_tags,
                book.personal_notes,
                *[edition.title for edition in book.editions],
                *[edition.language for edition in book.editions],
                *[edition.translator for edition in book.editions],
                *[edition.publisher for edition in book.editions],
                *[edition.isbn_10 for edition in book.editions],
                *[edition.isbn_13 for edition in book.editions],
                *[audiobook.title for audiobook in book.audiobooks],
                *[audiobook.language for audiobook in book.audiobooks],
                *[audiobook.narrator for audiobook in book.audiobooks],
                *[audiobook.publisher for audiobook in book.audiobooks],
                *[candidate.title for candidate in book.availability_candidates],
                *[candidate.language_guess for candidate in book.availability_candidates],
                *[quote.text for quote in book.quotes],
                *[quote.note for quote in book.quotes],
                *highlight_texts,
            ]
        )
    )
    return needle in haystack


def _matches_format(book: Book, value: str) -> bool:
    requested_raw = str(value or "").strip().casefold()
    requested = normalize_format(value)
    if not requested:
        return True
    formats = set(_book_formats(book))
    if requested_raw in {"missing", "no_digital", "no_digital_format"}:
        return not formats
    if requested_raw in {"pdf_only", "pdf-only"}:
        return formats == {"PDF"}
    if requested not in TEXT_FORMAT_PRIORITY:
        return True
    return requested in formats


def _matches_language(book: Book, value: str) -> bool:
    requested = normalize_title(value)
    if not requested:
        return True
    return any(requested in normalize_title(language) for language in _book_languages(book))


def _matches_audiobook(book: Book, value: str) -> bool:
    requested = str(value or "").strip().casefold()
    if requested not in {"yes", "no"}:
        return True
    has_audiobook = bool(book.audiobooks)
    return has_audiobook if requested == "yes" else not has_audiobook


def _matches_author(book: Book, value: str) -> bool:
    requested = normalize_title(value)
    if not requested:
        return True
    return any(requested == normalize_title(author) for author in _book_authors(book))


def _matches_translator(book: Book, value: str) -> bool:
    requested = normalize_title(value)
    if not requested:
        return True
    return any(
        requested == normalize_title(translator) for translator in _book_translators(book)
    )


def _matches_quotes(book: Book, value: str) -> bool:
    requested = str(value or "").strip().casefold()
    if requested not in {"yes", "no"}:
        return True
    has_quotes = bool(book.quotes)
    return has_quotes if requested == "yes" else not has_quotes


def _matches_highlights(book: Book, value: str, *, highlight_count: int = 0) -> bool:
    requested = str(value or "").strip().casefold()
    if requested not in {"yes", "no"}:
        return True
    has_highlights = highlight_count > 0
    return has_highlights if requested == "yes" else not has_highlights


def _matches_notes(book: Book, value: str) -> bool:
    requested = str(value or "").strip().casefold()
    if requested not in {"yes", "no"}:
        return True
    has_notes = bool(book.personal_notes.strip())
    return has_notes if requested == "yes" else not has_notes


def _matches_collection(book: Book, value: str) -> bool:
    requested = normalize_title(value)
    if not requested:
        return True
    return any(requested == normalize_title(collection) for collection in book.collections)


def _matches_metadata(book: Book, value: str) -> bool:
    requested = str(value or "").strip().casefold()
    if not requested:
        return True
    if requested == "inbox":
        return _metadata_needs_review(book)
    if requested == "missing_isbn":
        return book.metadata_status != "no_isbn" and not _has_isbn(book)
    if requested == "error":
        return book.metadata_status == "error"
    allowed_statuses = {
        "missing",
        "candidate_found",
        "needs_review",
        "verified",
        "no_isbn",
        "manual",
    }
    if requested in allowed_statuses:
        return book.metadata_status == requested
    return True


def _matches_review(book: Book, value: str) -> bool:
    requested = str(value or "").strip().casefold()
    if requested not in {"yes", "no"}:
        return True
    candidate_needs_review = any(
        candidate.review_state == "review_required" for candidate in book.availability_candidates
    )
    needs_review = _metadata_needs_review(book) or candidate_needs_review
    return needs_review if requested == "yes" else not needs_review


def _metadata_needs_review(book: Book) -> bool:
    return book.metadata_status in {
        "missing",
        "candidate_found",
        "needs_review",
        "error",
    }


def _has_isbn(book: Book) -> bool:
    return (
        bool(book.isbn_10 or book.isbn_13)
        or any(edition.isbn_10 or edition.isbn_13 for edition in book.editions)
    )


def _book_languages(book: Book) -> list[str]:
    metadata_state = book.metadata_state if isinstance(book.metadata_state, dict) else {}
    languages = [
        book.edition_language,
        book.original_language,
        *[edition.language for edition in book.editions],
        *[audiobook.language for audiobook in book.audiobooks],
        *[candidate.language_guess for candidate in book.availability_candidates],
    ]
    legacy_languages = metadata_state.get("audiobook_languages", [])
    if isinstance(legacy_languages, list):
        languages.extend(str(value) for value in legacy_languages)
    return [language for language in languages if language]


def _book_authors(book: Book) -> list[str]:
    metadata_state = book.metadata_state if isinstance(book.metadata_state, dict) else {}
    authors = [*book.authors, *book.additional_authors]
    legacy_authors = metadata_state.get("authors", [])
    if isinstance(legacy_authors, list):
        authors.extend(str(value) for value in legacy_authors)
    return [author for author in authors if author]


def _book_translators(book: Book) -> list[str]:
    metadata_state = book.metadata_state if isinstance(book.metadata_state, dict) else {}
    translators = [
        book.translator,
        *[edition.translator for edition in book.editions],
    ]
    legacy_translator = metadata_state.get("translator", "")
    if legacy_translator:
        translators.append(str(legacy_translator))
    return [translator for translator in translators if translator]


def _book_formats(book: Book) -> list[str]:
    metadata_state = book.metadata_state if isinstance(book.metadata_state, dict) else {}
    formats = [
        asset.format
        for edition in book.editions
        for asset in edition.text_assets
        if _asset_available(asset)
    ]
    legacy_formats = metadata_state.get("formats_available", [])
    if isinstance(legacy_formats, list):
        formats.extend(str(value) for value in legacy_formats)
    return sort_text_formats(tuple(formats))


def _asset_available(asset: TextAsset) -> bool:
    return asset.availability_status != "rejected"


def _book_highlight_cache(books: list[Book]) -> tuple[dict[str, tuple[str, ...]], dict[str, int]]:
    from app.books.book_quotes import BookQuotesSnapshotService, project_book_quotes

    snapshot = BookQuotesSnapshotService.store().load()
    text_map: dict[str, list[str]] = {}
    count_map: dict[str, int] = {}
    for projection in project_book_quotes(snapshot, books):
        if projection.match.state != "matched":
            continue
        book_id = str(projection.match.book_id or "")
        text = str(projection.item.payload.get("quote") or "").strip()
        if not book_id or not text:
            continue
        text_map.setdefault(book_id, []).append(text)
        count_map[book_id] = count_map.get(book_id, 0) + 1
    return (
        {book_id: tuple(values) for book_id, values in text_map.items()},
        count_map,
    )


def _book_select():
    return db.select(Book).options(
        selectinload(Book.quotes),
        selectinload(Book.editions).selectinload(BookEdition.text_assets),
        selectinload(Book.audiobooks).selectinload(AudiobookEdition.assets),
        selectinload(Book.availability_candidates),
    )
