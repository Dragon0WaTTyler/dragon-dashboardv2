from __future__ import annotations

from app.books.models import Book, BookEdition

PRIMARY_EDITION_FIELD_MAP = {
    "cover_url": "cover_url",
    "edition_language": "language",
    "translator": "translator",
    "publisher": "publisher",
    "published_year": "publication_year",
    "page_count": "page_count",
    "isbn_10": "isbn_10",
    "isbn_13": "isbn_13",
}


def primary_book_edition(book: Book) -> BookEdition | None:
    primary = next((edition for edition in book.editions if edition.primary), None)
    return primary or (book.editions[0] if book.editions else None)


def effective_book_value(book: Book, field: str):
    value = getattr(book, field)
    if value not in (None, "", [], 0):
        return value
    edition_field = PRIMARY_EDITION_FIELD_MAP.get(field)
    if not edition_field:
        return value
    edition = primary_book_edition(book)
    if edition is None:
        return value
    fallback = getattr(edition, edition_field, value)
    return fallback if fallback not in (None, "", [], 0) else value
