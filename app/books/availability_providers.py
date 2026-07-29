from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests

from app.books.availability import AvailabilityCandidateError, parse_candidate_text
from app.books.matching import normalize_title, title_similarity
from app.books.models import Book
from app.books.primary_editions import effective_book_value
from app.books.priorities import TEXT_FORMAT_PRIORITY

DEFAULT_JACKETT_BOOK_CATEGORIES = "7000"


class AvailabilityProviderError(RuntimeError):
    """A credential-safe failure from a Knowledge availability provider."""


@dataclass(frozen=True)
class AvailabilitySearchResult:
    provider: str
    title: str
    format_guess: str
    language_guess: str
    size_bytes: int
    source_reference: str
    match_confidence: str
    metadata_json: dict[str, Any]


class JackettBookAvailabilityProvider:
    provider_name = "jackett"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        min_seeders: int = 5,
        categories: str = DEFAULT_JACKETT_BOOK_CATEGORIES,
        session: requests.Session | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.api_key = api_key.strip()
        self.min_seeders = max(0, int(min_seeders))
        self.categories = str(categories or "").strip()
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def search(self, book: Book, *, limit: int = 12) -> list[AvailabilitySearchResult]:
        if not self.configured:
            raise AvailabilityProviderError("Jackett is not configured.")
        rows: list[dict[str, Any]] = []
        for query in _book_queries(book)[:8]:
            params = {"apikey": self.api_key, "Query": query}
            if self.categories:
                params["Category"] = self.categories
            try:
                response = self.session.get(
                    urljoin(self.base_url, "api/v2.0/indexers/all/results"),
                    params=params,
                    headers={"Accept": "application/json"},
                    timeout=self.timeout_seconds,
                )
                if not response.ok:
                    raise AvailabilityProviderError(
                        f"Jackett returned HTTP {response.status_code}."
                    )
                rows.extend(_parse_jackett_json(response.json(), query=query))
            except (requests.RequestException, ValueError) as exc:
                raise AvailabilityProviderError("Jackett is unavailable.") from exc
        return _ranked_book_results(book, rows, min_seeders=self.min_seeders, limit=limit)


def _book_queries(book: Book) -> list[str]:
    authors = [str(author).strip() for author in book.authors if str(author).strip()]
    author = authors[0] if authors else ""
    language = (
        str(effective_book_value(book, "edition_language") or "")
        or book.original_language
        or ""
    )
    base_parts = [book.title, author, language]
    base = " ".join(part for part in base_parts if part).strip()
    queries = [base, f"{book.title} {author}".strip(), book.title]
    for text_format in TEXT_FORMAT_PRIORITY:
        queries.append(f"{base} {text_format}".strip())
    return _dedupe(queries)


def _parse_jackett_json(payload: Any, *, query: str) -> list[dict[str, Any]]:
    rows = payload.get("Results", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("Unexpected Jackett response")
    parsed = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("Title") or "Untitled release")
        parsed.append(
            {
                "title": title,
                "seeders": _integer(row.get("Seeders")),
                "leechers": _integer(row.get("Peers") or row.get("Leechers")),
                "size_bytes": _integer(row.get("Size")),
                "tracker": str(row.get("Tracker") or row.get("TrackerId") or "Unknown"),
                "published": row.get("PublishDate") or row.get("FirstSeen"),
                "source_reference": _safe_reference(row),
                "query": query,
            }
        )
    return parsed


def _ranked_book_results(
    book: Book, rows: list[dict[str, Any]], *, min_seeders: int, limit: int
) -> list[AvailabilitySearchResult]:
    unique: dict[tuple[str, str, str], tuple[int, AvailabilitySearchResult]] = {}
    for row in rows:
        if row["seeders"] < min_seeders:
            continue
        try:
            parsed = parse_candidate_text(provider="jackett", raw_text=row["title"])
        except AvailabilityCandidateError:
            continue
        score, confidence = _match_score(book, row["title"], parsed.title, row)
        result = AvailabilitySearchResult(
            provider="jackett",
            title=parsed.title,
            format_guess=parsed.format_guess,
            language_guess=parsed.language_guess,
            size_bytes=row["size_bytes"] or parsed.size_bytes,
            source_reference=row["source_reference"],
            match_confidence=confidence,
            metadata_json={
                "tracker": row["tracker"],
                "seeders": row["seeders"],
                "leechers": row["leechers"],
                "published": row["published"],
                "query": row["query"],
                "match_score": score,
            },
        )
        key = (
            result.source_reference or normalize_title(result.title),
            result.format_guess,
            normalize_title(result.title),
        )
        previous = unique.get(key)
        if previous is None or score > previous[0]:
            unique[key] = (score, result)
    ranked = sorted(
        unique.values(),
        key=lambda item: (
            TEXT_FORMAT_PRIORITY.index(item[1].format_guess),
            -item[0],
            item[1].title.casefold(),
        ),
    )
    return [result for _, result in ranked[: max(1, min(int(limit), 30))]]


def _match_score(
    book: Book, raw_title: str, parsed_title: str, row: dict[str, Any]
) -> tuple[int, str]:
    similarity = title_similarity(book.title, parsed_title)
    normalized_raw = normalize_title(raw_title)
    author_present = any(
        normalize_title(author) and normalize_title(author) in normalized_raw
        for author in book.authors
    )
    score = int(similarity * 500) + min(int(row["seeders"]), 60) * 3
    if author_present:
        score += 120
    confidence = "low"
    if similarity >= 0.9 and author_present:
        confidence = "high"
    elif similarity >= 0.74 or author_present:
        confidence = "medium"
    return score, confidence


def _safe_reference(row: dict[str, Any]) -> str:
    reference = str(
        row.get("Details")
        or row.get("Guid")
        or row.get("Link")
        or row.get("MagnetUri")
        or row.get("MagnetURI")
        or ""
    ).strip()
    if reference.startswith("magnet:?"):
        return _magnet_reference(reference)
    parsed = urlsplit(reference)
    if parsed.scheme not in {"http", "https"}:
        return reference[:2000]
    query = urlencode(
        [(key, value) for key, value in parse_qsl(parsed.query) if key.lower() != "apikey"]
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))[:2000]


def _magnet_reference(value: str) -> str:
    match = re.search(r"(?:\?|&)xt=urn:btih:([^&]+)", value, flags=re.IGNORECASE)
    return f"magnet:btih:{match.group(1).casefold()}" if match else "magnet:btih"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for value in values:
        cleaned = " ".join(str(value or "").split())
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        results.append(cleaned)
    return results


def _integer(value: Any) -> int:
    try:
        return int(value) if value not in {None, ""} else 0
    except (TypeError, ValueError):
        return 0
