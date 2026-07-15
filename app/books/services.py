from __future__ import annotations

from app.books.models import Book, Quote
from app.extensions import db
from app.history.services import HistoryService
from app.shared.text import text_direction
from app.shared.time import utc_iso

BOOK_STATUSES = {"want_to_read", "reading", "finished", "paused"}


def book_item(book: Book) -> dict:
    percent = round(book.current_page / book.page_count * 100) if book.page_count else 0
    direction_source = " ".join([book.title, *book.authors])
    return {
        "id": book.id,
        "title": book.title,
        "authors": book.authors,
        "cover_url": book.cover_url,
        "status": book.status,
        "current_page": book.current_page,
        "page_count": book.page_count,
        "progress_percent": min(percent, 100),
        "personal_score": book.personal_score,
        "direction": text_direction(direction_source),
    }


def book_detail(book: Book) -> dict:
    return {
        **book_item(book),
        "description": book.description,
        "published_year": book.published_year,
        "source": book.source,
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
        "metadata_state": book.metadata_state,
    }


class BookService:
    @staticmethod
    def current_book() -> dict | None:
        from app.books.repositories import BookRepository

        books = BookRepository.list(status="reading")
        return book_item(books[0]) if books else None

    @staticmethod
    def save_progress(book: Book, *, status: str, current_page: int) -> None:
        if status not in BOOK_STATUSES:
            raise ValueError("Unknown book status.")
        if current_page < 0 or (book.page_count and current_page > book.page_count):
            raise ValueError("Page progress is outside the book range.")
        book.status = status
        book.current_page = current_page
        book.history = [*book.history, {"event": "progress", "at": utc_iso(), "page": current_page}]
        HistoryService.record(
            domain="books",
            entity_type="book",
            entity_id=book.id,
            event_type="progress",
            label=f"{book.title}: page {current_page}",
            metadata={"status": status, "current_page": current_page},
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
