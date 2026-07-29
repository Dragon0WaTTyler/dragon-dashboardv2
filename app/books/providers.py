from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import requests

from app.books.matching import split_isbns

OPEN_LIBRARY_BASE_URL = "https://openlibrary.org"
GOOGLE_BOOKS_BASE_URL = "https://www.googleapis.com/books/v1"


class BookMetadataProviderError(RuntimeError):
    """A safe metadata lookup failure that never exposes URLs or credentials."""


@dataclass(frozen=True, slots=True)
class MetadataCandidate:
    source: str
    title: str = ""
    authors: list[str] = field(default_factory=list)
    overview: str = ""
    cover_url: str = ""
    subjects: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    language: str = ""
    publisher: str = ""
    published_year: int | None = None
    page_count: int = 0
    isbn_10: str = ""
    isbn_13: str = ""
    openlibrary_work_id: str = ""
    openlibrary_edition_id: str = ""
    google_books_volume_id: str = ""
    confidence: str = "medium"

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "title": self.title,
            "authors": self.authors,
            "overview": self.overview,
            "cover_url": self.cover_url,
            "subjects": self.subjects,
            "genres": self.genres,
            "language": self.language,
            "publisher": self.publisher,
            "published_year": self.published_year,
            "page_count": self.page_count,
            "isbn_10": self.isbn_10,
            "isbn_13": self.isbn_13,
            "openlibrary_work_id": self.openlibrary_work_id,
            "openlibrary_edition_id": self.openlibrary_edition_id,
            "google_books_volume_id": self.google_books_volume_id,
            "confidence": self.confidence,
        }


class OpenLibraryProvider:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    def lookup(
        self,
        *,
        title: str,
        authors: list[str] | tuple[str, ...] = (),
        isbn: str = "",
        language: str = "",
    ) -> list[MetadataCandidate]:
        params: dict[str, str | int] = {
            "limit": 5,
            "fields": ",".join(
                [
                    "key",
                    "title",
                    "author_name",
                    "first_publish_year",
                    "language",
                    "publisher",
                    "isbn",
                    "cover_i",
                    "edition_key",
                    "subject",
                    "number_of_pages_median",
                ]
            ),
        }
        if isbn:
            params["isbn"] = isbn
        else:
            params["title"] = title
            if authors:
                params["author"] = authors[0]
            if language:
                params["language"] = language
        payload = self._get_json("/search.json", params)
        docs = payload.get("docs") if isinstance(payload, dict) else None
        if not isinstance(docs, list):
            raise BookMetadataProviderError("Open Library returned an invalid search response.")
        return [
            self._candidate(doc, exact_isbn=bool(isbn))
            for doc in docs
            if isinstance(doc, dict)
        ]

    def _get_json(self, path: str, params: dict[str, str | int]) -> dict[str, Any]:
        try:
            response = self.session.get(
                f"{OPEN_LIBRARY_BASE_URL}{path}",
                params=params,
                headers={"Accept": "application/json", "User-Agent": "DragonV2/1.0"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise BookMetadataProviderError("Open Library lookup is unavailable.") from exc
        if not isinstance(payload, dict):
            raise BookMetadataProviderError("Open Library returned an invalid response.")
        return payload

    @staticmethod
    def _candidate(doc: dict[str, Any], *, exact_isbn: bool) -> MetadataCandidate:
        isbn_10, isbn_13 = split_isbns([str(value) for value in doc.get("isbn") or []])
        cover_id = doc.get("cover_i")
        edition_keys = [str(value) for value in doc.get("edition_key") or [] if value]
        subjects = [str(value) for value in (doc.get("subject") or [])[:8] if value]
        publishers = [str(value) for value in (doc.get("publisher") or []) if value]
        languages = [str(value) for value in (doc.get("language") or []) if value]
        return MetadataCandidate(
            source="Open Library",
            title=str(doc.get("title") or "").strip(),
            authors=[str(value) for value in (doc.get("author_name") or [])[:6] if value],
            cover_url=(
                f"https://covers.openlibrary.org/b/id/{int(cover_id)}-L.jpg"
                if isinstance(cover_id, int)
                else ""
            ),
            subjects=subjects,
            language=languages[0] if languages else "",
            publisher=publishers[0] if publishers else "",
            published_year=_optional_int(doc.get("first_publish_year")),
            page_count=_optional_int(doc.get("number_of_pages_median")) or 0,
            isbn_10=isbn_10,
            isbn_13=isbn_13,
            openlibrary_work_id=str(doc.get("key") or "").removeprefix("/works/"),
            openlibrary_edition_id=edition_keys[0] if edition_keys else "",
            confidence="exact_isbn" if exact_isbn else "high",
        )


class GoogleBooksProvider:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    def lookup(
        self,
        *,
        title: str,
        authors: list[str] | tuple[str, ...] = (),
        isbn: str = "",
        language: str = "",
    ) -> list[MetadataCandidate]:
        if isbn:
            query = f"isbn:{isbn}"
        else:
            parts = [f"intitle:{title}"]
            if authors:
                parts.append(f"inauthor:{authors[0]}")
            query = " ".join(parts)
        params = {"q": query, "maxResults": 5, "printType": "books"}
        if language:
            params["langRestrict"] = language[:2].lower()
        payload = self._get_json("/volumes", params)
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return []
        return [
            self._candidate(item, exact_isbn=bool(isbn))
            for item in items
            if isinstance(item, dict)
        ]

    def _get_json(self, path: str, params: dict[str, str | int]) -> dict[str, Any]:
        try:
            response = self.session.get(
                f"{GOOGLE_BOOKS_BASE_URL}{path}?{urlencode(params)}",
                headers={"Accept": "application/json", "User-Agent": "DragonV2/1.0"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise BookMetadataProviderError("Google Books lookup is unavailable.") from exc
        if not isinstance(payload, dict):
            raise BookMetadataProviderError("Google Books returned an invalid response.")
        return payload

    @staticmethod
    def _candidate(item: dict[str, Any], *, exact_isbn: bool) -> MetadataCandidate:
        info = item.get("volumeInfo") or {}
        identifiers = info.get("industryIdentifiers") or []
        isbn_10, isbn_13 = split_isbns(
            [
                str(identifier.get("identifier") or "")
                for identifier in identifiers
                if isinstance(identifier, dict)
            ]
        )
        image_links = info.get("imageLinks") or {}
        categories = [str(value) for value in (info.get("categories") or [])[:8] if value]
        return MetadataCandidate(
            source="Google Books",
            title=str(info.get("title") or "").strip(),
            authors=[str(value) for value in (info.get("authors") or [])[:6] if value],
            overview=str(info.get("description") or "").strip(),
            cover_url=str(image_links.get("thumbnail") or image_links.get("smallThumbnail") or ""),
            subjects=categories,
            language=str(info.get("language") or "").strip(),
            publisher=str(info.get("publisher") or "").strip(),
            published_year=_year(info.get("publishedDate")),
            page_count=_optional_int(info.get("pageCount")) or 0,
            isbn_10=isbn_10,
            isbn_13=isbn_13,
            google_books_volume_id=str(item.get("id") or "").strip(),
            confidence="exact_isbn" if exact_isbn else "medium",
        )


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None


def _year(value: object) -> int | None:
    text = str(value or "")
    return int(text[:4]) if text[:4].isdigit() else None
