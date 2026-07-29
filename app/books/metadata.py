from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.books.matching import normalize_isbn, title_similarity
from app.books.models import Book
from app.books.primary_editions import effective_book_value
from app.books.providers import (
    BookMetadataProviderError,
    GoogleBooksProvider,
    MetadataCandidate,
    OpenLibraryProvider,
)
from app.extensions import db
from app.shared.time import utc_now

METADATA_FIELDS = {
    "title": "title",
    "overview": "description",
    "cover_url": "cover_url",
    "publisher": "publisher",
    "published_year": "published_year",
    "page_count": "page_count",
    "isbn_10": "isbn_10",
    "isbn_13": "isbn_13",
    "subjects": "subjects",
}
LANGUAGE_ALIASES = {
    "ar": "arabic",
    "ara": "arabic",
    "arabic": "arabic",
    "العربية": "arabic",
    "عربي": "arabic",
    "en": "english",
    "eng": "english",
    "english": "english",
    "fr": "french",
    "fre": "french",
    "fra": "french",
    "french": "french",
    "es": "spanish",
    "spa": "spanish",
    "spanish": "spanish",
    "de": "german",
    "ger": "german",
    "deu": "german",
    "german": "german",
}
PERSONAL_FIELDS = {
    "status",
    "current_page",
    "personal_score",
    "favorite",
    "personal_tags",
    "collections",
    "personal_notes",
}


class MetadataProvider(Protocol):
    def lookup(
        self,
        *,
        title: str,
        authors: list[str] | tuple[str, ...] = (),
        isbn: str = "",
        language: str = "",
    ) -> list[MetadataCandidate]: ...


@dataclass(frozen=True, slots=True)
class MetadataProposal:
    candidate: MetadataCandidate
    fill: dict[str, object]
    conflicts: dict[str, dict[str, object]]
    status: str
    confidence: str

    def as_dict(self) -> dict:
        return {
            "candidate": self.candidate.as_dict(),
            "fill": self.fill,
            "conflicts": self.conflicts,
            "status": self.status,
            "confidence": self.confidence,
        }


class BookMetadataService:
    @staticmethod
    def preview(
        book: Book,
        providers: list[MetadataProvider] | tuple[MetadataProvider, ...] | None = None,
    ) -> MetadataProposal | None:
        candidates = BookMetadataService.candidates(book, providers)
        if not candidates:
            return None
        candidate = candidates[0]
        fill, conflicts = _merge_plan(book, candidate)
        status, confidence = _proposal_state(book, candidate)
        return MetadataProposal(
            candidate=candidate,
            fill=fill,
            conflicts=conflicts,
            status=status,
            confidence=confidence,
        )

    @staticmethod
    def candidates(
        book: Book,
        providers: list[MetadataProvider] | tuple[MetadataProvider, ...] | None = None,
    ) -> list[MetadataCandidate]:
        providers = list(providers or [OpenLibraryProvider(), GoogleBooksProvider()])
        queries = _queries(book)
        results: list[MetadataCandidate] = []
        errors: list[str] = []
        for query in queries:
            for provider in providers:
                try:
                    provider_results = provider.lookup(**query)
                except BookMetadataProviderError as exc:
                    errors.append(str(exc))
                    continue
                results.extend(_acceptable(book, provider_results, exact_isbn=bool(query["isbn"])))
                if results and query["isbn"]:
                    return _ranked(book, results)
            if results:
                return _ranked(book, results)
        if errors:
            book.metadata_state = {
                **(book.metadata_state or {}),
                "last_metadata_errors": errors[-3:],
            }
        return []

    @staticmethod
    def apply_fill(book: Book, proposal: MetadataProposal) -> None:
        _apply_fill(book, proposal)
        db.session.commit()

    @staticmethod
    def store_preview(book: Book, proposal: MetadataProposal) -> None:
        book.metadata_state = {
            **(book.metadata_state or {}),
            "metadata_preview": proposal.as_dict(),
        }
        book.metadata_status = proposal.status
        book.metadata_confidence = proposal.confidence
        book.metadata_sources = list(
            dict.fromkeys([*(book.metadata_sources or []), proposal.candidate.source])
        )
        book.last_metadata_refresh_at = utc_now()
        db.session.commit()

    @staticmethod
    def clear_preview(book: Book) -> None:
        state = dict(book.metadata_state or {})
        state.pop("metadata_preview", None)
        book.metadata_state = state
        db.session.commit()

    @staticmethod
    def apply_stored_preview(book: Book) -> None:
        payload = (book.metadata_state or {}).get("metadata_preview")
        if not isinstance(payload, dict):
            raise ValueError("No metadata preview is ready to apply.")
        proposal = _proposal_from_payload(payload)
        _apply_fill(book, proposal)
        state = dict(book.metadata_state or {})
        state.pop("metadata_preview", None)
        state["last_metadata_preview"] = {**payload, "applied_at": utc_now().isoformat()}
        book.metadata_state = state
        db.session.commit()


def _apply_fill(book: Book, proposal: MetadataProposal) -> None:
    for field, value in proposal.fill.items():
        if field in PERSONAL_FIELDS:
            continue
        if field == "openlibrary_work_id" and value:
            book.external_ids = {**(book.external_ids or {}), "openlibrary_work_id": value}
        elif field == "openlibrary_edition_id" and value:
            book.external_ids = {**(book.external_ids or {}), "openlibrary_edition_id": value}
        elif field == "google_books_volume_id" and value:
            book.external_ids = {**(book.external_ids or {}), "google_books_volume_id": value}
        elif hasattr(book, field):
            setattr(book, field, value)
    book.metadata_status = proposal.status
    book.metadata_confidence = proposal.confidence
    book.metadata_sources = list(
        dict.fromkeys([*(book.metadata_sources or []), proposal.candidate.source])
    )
    book.last_metadata_refresh_at = utc_now()


def _queries(book: Book) -> list[dict]:
    isbns = [
        normalize_isbn(effective_book_value(book, "isbn_13")),
        normalize_isbn(effective_book_value(book, "isbn_10")),
    ]
    language = str(effective_book_value(book, "edition_language") or "")
    queries = [
        {
            "title": book.title,
            "authors": book.authors,
            "isbn": isbn,
            "language": language,
        }
        for isbn in isbns
        if isbn
    ]
    queries.append(
        {
            "title": book.title,
            "authors": book.authors,
            "isbn": "",
            "language": language,
        }
    )
    return queries


def _acceptable(
    book: Book, candidates: list[MetadataCandidate], *, exact_isbn: bool
) -> list[MetadataCandidate]:
    accepted = []
    for candidate in candidates:
        if exact_isbn:
            accepted.append(candidate)
            continue
        similarity = title_similarity(book.title, candidate.title)
        author_overlap = {
            value.casefold() for value in book.authors
        } & {value.casefold() for value in candidate.authors}
        if (
            similarity >= 0.72
            and (author_overlap or not book.authors)
            and _candidate_language_allowed(book, candidate)
        ):
            accepted.append(candidate)
    return accepted


def _ranked(book: Book, candidates: list[MetadataCandidate]) -> list[MetadataCandidate]:
    confidence_score = {"exact_isbn": 300, "high": 200, "medium": 100, "low": 0}
    return sorted(
        candidates,
        key=lambda candidate: (
            confidence_score.get(candidate.confidence, 50),
            title_similarity(book.title, candidate.title),
            bool(candidate.isbn_13 or candidate.isbn_10),
            bool(candidate.cover_url),
        ),
        reverse=True,
    )


def _merge_plan(book: Book, candidate: MetadataCandidate) -> tuple[dict[str, object], dict]:
    fill: dict[str, object] = {}
    conflicts: dict[str, dict[str, object]] = {}
    candidate_values = candidate.as_dict()
    protected_fields = _protected_fallback_fields(book, candidate)
    for candidate_field, book_field in METADATA_FIELDS.items():
        if book_field in protected_fields:
            continue
        value = candidate_values.get(candidate_field)
        if value in (None, "", [], 0):
            continue
        current = getattr(book, book_field)
        if current in (None, "", [], 0):
            fill[book_field] = value
        elif current != value:
            conflicts[book_field] = {"current": current, "candidate": value}
    for external_field in (
        "openlibrary_work_id",
        "openlibrary_edition_id",
        "google_books_volume_id",
    ):
        value = candidate_values.get(external_field)
        if value and not (book.external_ids or {}).get(external_field):
            fill[external_field] = value
    return fill, conflicts


def _proposal_state(book: Book, candidate: MetadataCandidate) -> tuple[str, str]:
    if candidate.confidence == "exact_isbn":
        return "verified", "exact_isbn"
    if _fallback_needs_review(book, candidate):
        return "needs_review", "low"
    return "candidate_found", candidate.confidence


def _fallback_needs_review(book: Book, candidate: MetadataCandidate) -> bool:
    return (
        candidate.confidence != "exact_isbn"
        and _language_sensitive(book)
        and not _candidate_language_matches(book, candidate)
    )


def _protected_fallback_fields(book: Book, candidate: MetadataCandidate) -> set[str]:
    if not _fallback_needs_review(book, candidate):
        return set()
    return {"isbn_10", "isbn_13"}


def _candidate_language_allowed(book: Book, candidate: MetadataCandidate) -> bool:
    book_language = _normalized_language(str(effective_book_value(book, "edition_language") or ""))
    candidate_language = _normalized_language(candidate.language)
    return not book_language or not candidate_language or book_language == candidate_language


def _candidate_language_matches(book: Book, candidate: MetadataCandidate) -> bool:
    book_language = _normalized_language(str(effective_book_value(book, "edition_language") or ""))
    candidate_language = _normalized_language(candidate.language)
    return bool(book_language and candidate_language and book_language == candidate_language)


def _language_sensitive(book: Book) -> bool:
    return bool(
        effective_book_value(book, "edition_language")
        or effective_book_value(book, "translator")
        or book.original_language
    )


def _normalized_language(value: str) -> str:
    text = str(value or "").strip().casefold()
    return LANGUAGE_ALIASES.get(text, text)


def _proposal_from_payload(payload: dict) -> MetadataProposal:
    fill = payload.get("fill")
    if not isinstance(fill, dict):
        raise ValueError("Metadata preview is missing its fill plan.")
    conflicts = payload.get("conflicts")
    candidate_data = payload.get("candidate")
    candidate_payload = candidate_data if isinstance(candidate_data, dict) else {}
    return MetadataProposal(
        candidate=_candidate_from_payload(candidate_payload),
        fill=fill,
        conflicts=conflicts if isinstance(conflicts, dict) else {},
        status=str(payload.get("status") or "candidate_found"),
        confidence=str(payload.get("confidence") or "medium"),
    )


def _candidate_from_payload(data: dict) -> MetadataCandidate:
    return MetadataCandidate(
        source=str(data.get("source") or "Unknown provider"),
        title=str(data.get("title") or ""),
        authors=_string_list(data.get("authors")),
        overview=str(data.get("overview") or ""),
        cover_url=str(data.get("cover_url") or ""),
        subjects=_string_list(data.get("subjects")),
        genres=_string_list(data.get("genres")),
        language=str(data.get("language") or ""),
        publisher=str(data.get("publisher") or ""),
        published_year=_optional_int(data.get("published_year")),
        page_count=_optional_int(data.get("page_count")) or 0,
        isbn_10=str(data.get("isbn_10") or ""),
        isbn_13=str(data.get("isbn_13") or ""),
        openlibrary_work_id=str(data.get("openlibrary_work_id") or ""),
        openlibrary_edition_id=str(data.get("openlibrary_edition_id") or ""),
        google_books_volume_id=str(data.get("google_books_volume_id") or ""),
        confidence=str(data.get("confidence") or "medium"),
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item not in (None, "")]


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None
