from __future__ import annotations

import re
from dataclasses import dataclass

from app.books.models import AvailabilityCandidate, Book
from app.books.priorities import TEXT_FORMAT_PRIORITY, normalize_format
from app.extensions import db

ALLOWED_AVAILABILITY_PROVIDERS = {"local", "telegram", "jackett"}
ALLOWED_REVIEW_STATES = {"review_required", "confirmed", "rejected"}
ALLOWED_MATCH_CONFIDENCE = {"verified", "high", "medium", "low", "needs_review"}
SOURCE_REFERENCE_LIMIT = 2000

FORMAT_PATTERN = re.compile(
    r"(?:\b(?P<word>KFX|AZW3|EPUB|PDF)\b|[.](?P<extension>kfx|azw3|epub|pdf)\b)",
    re.IGNORECASE,
)
SIZE_PATTERN = re.compile(
    r"\b(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>kb|kib|mb|mib|gb|gib)\b",
    re.IGNORECASE,
)
URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
LANGUAGE_HINTS = (
    ("Arabic", re.compile(r"\b(ar|arabic)\b|عربي|العربية", re.IGNORECASE)),
    ("English", re.compile(r"\b(en|eng|english)\b", re.IGNORECASE)),
    ("French", re.compile(r"\b(fr|fre|fra|french|francais|français)\b", re.IGNORECASE)),
    ("Spanish", re.compile(r"\b(es|spa|spanish|espanol|español)\b", re.IGNORECASE)),
    ("German", re.compile(r"\b(de|ger|deu|german|deutsch)\b", re.IGNORECASE)),
)
TITLE_NOISE_PATTERN = re.compile(
    r"\b(kfx|azw3|epub|pdf|kb|kib|mb|mib|gb|gib|download|ebook)\b",
    re.IGNORECASE,
)
ARABIC_TITLE_NOISE_PATTERN = re.compile(r"(تحميل|كتاب|نسخة|كاملة)")


class AvailabilityCandidateError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedAvailabilityCandidate:
    provider: str
    title: str
    format_guess: str
    language_guess: str
    size_bytes: int
    source_reference: str


class BookAvailabilityService:
    @staticmethod
    def add_candidate(
        book: Book,
        *,
        provider: str,
        title: str,
        format_guess: str,
        language_guess: str = "",
        source_reference: str = "",
        size_bytes: int = 0,
        match_confidence: str = "needs_review",
        metadata_json: dict | None = None,
    ) -> AvailabilityCandidate:
        provider = str(provider or "").strip().casefold()
        if provider not in ALLOWED_AVAILABILITY_PROVIDERS:
            raise AvailabilityCandidateError("Unknown availability provider.")
        normalized_title = " ".join(str(title or "").split())
        if not normalized_title:
            raise AvailabilityCandidateError("Candidate title is required.")
        normalized_format = normalize_format(format_guess)
        if normalized_format not in TEXT_FORMAT_PRIORITY:
            raise AvailabilityCandidateError("Candidate format must be KFX, AZW3, EPUB, or PDF.")
        normalized_confidence = str(match_confidence or "needs_review").strip().casefold()
        if normalized_confidence not in ALLOWED_MATCH_CONFIDENCE:
            normalized_confidence = "needs_review"
        candidate = AvailabilityCandidate(
            book=book,
            provider=provider,
            title=normalized_title,
            format_guess=normalized_format,
            language_guess=str(language_guess or "").strip(),
            size_bytes=_normalize_size_bytes(size_bytes),
            source_reference=str(source_reference or "").strip()[:SOURCE_REFERENCE_LIMIT],
            match_confidence=normalized_confidence,
            review_state="review_required",
            metadata_json=metadata_json or {},
        )
        db.session.add(candidate)
        db.session.commit()
        return candidate

    @staticmethod
    def add_candidate_from_text(
        book: Book, *, provider: str, raw_text: str
    ) -> AvailabilityCandidate:
        parsed = parse_candidate_text(provider=provider, raw_text=raw_text)
        return BookAvailabilityService.add_candidate(
            book,
            provider=parsed.provider,
            title=parsed.title,
            format_guess=parsed.format_guess,
            language_guess=parsed.language_guess,
            source_reference=parsed.source_reference,
            size_bytes=parsed.size_bytes,
        )

    @staticmethod
    def add_provider_results(book: Book, results: list[object]) -> tuple[int, int]:
        created = 0
        skipped = 0
        for result in results:
            title = _result_value(result, "title")
            format_guess = _result_value(result, "format_guess")
            source_reference = _result_value(result, "source_reference")
            provider = _result_value(result, "provider") or "jackett"
            if _has_duplicate_candidate(book, provider, title, format_guess, source_reference):
                skipped += 1
                continue
            BookAvailabilityService.add_candidate(
                book,
                provider=provider,
                title=title,
                format_guess=format_guess,
                language_guess=_result_value(result, "language_guess"),
                source_reference=source_reference,
                size_bytes=_result_value(result, "size_bytes"),
                match_confidence=_result_value(result, "match_confidence") or "needs_review",
                metadata_json=_result_value(result, "metadata_json") or {},
            )
            created += 1
        return created, skipped

    @staticmethod
    def set_review_state(
        book: Book, *, candidate_id: str, review_state: str
    ) -> AvailabilityCandidate:
        normalized_state = str(review_state or "").strip().casefold()
        if normalized_state not in ALLOWED_REVIEW_STATES:
            raise AvailabilityCandidateError("Unknown availability review state.")
        candidate = _candidate_for_book(book, candidate_id)
        candidate.review_state = normalized_state
        candidate.match_confidence = "high" if normalized_state == "confirmed" else "needs_review"
        db.session.commit()
        return candidate


def _candidate_for_book(book: Book, candidate_id: str) -> AvailabilityCandidate:
    for candidate in book.availability_candidates:
        if candidate.id == candidate_id:
            return candidate
    raise AvailabilityCandidateError("Availability candidate was not found for this book.")


def parse_candidate_text(*, provider: str, raw_text: str) -> ParsedAvailabilityCandidate:
    normalized_provider = str(provider or "").strip().casefold()
    if normalized_provider not in ALLOWED_AVAILABILITY_PROVIDERS:
        raise AvailabilityCandidateError("Unknown availability provider.")

    text = str(raw_text or "").strip()
    if not text:
        raise AvailabilityCandidateError("Paste a provider result or filename first.")

    format_guess = _detect_format(text)
    if not format_guess:
        raise AvailabilityCandidateError("Could not detect a supported text format.")

    return ParsedAvailabilityCandidate(
        provider=normalized_provider,
        title=_detect_title(text),
        format_guess=format_guess,
        language_guess=_detect_language(text),
        size_bytes=_detect_size_bytes(text),
        source_reference=_detect_source_reference(text),
    )


def _detect_format(text: str) -> str:
    match = FORMAT_PATTERN.search(text)
    if not match:
        return ""
    return normalize_format(match.group("word") or match.group("extension"))


def _detect_language(text: str) -> str:
    for label, pattern in LANGUAGE_HINTS:
        if pattern.search(text):
            return label
    return ""


def _detect_size_bytes(text: str) -> int:
    match = SIZE_PATTERN.search(text)
    if not match:
        return 0
    number = float(match.group("number").replace(",", "."))
    unit = match.group("unit").casefold()
    multiplier = 1024
    if unit in {"mb", "mib"}:
        multiplier = 1024**2
    elif unit in {"gb", "gib"}:
        multiplier = 1024**3
    return int(number * multiplier)


def _detect_source_reference(text: str) -> str:
    match = URL_PATTERN.search(text)
    if match:
        return match.group(0).strip(").,]")
    return text[:SOURCE_REFERENCE_LIMIT]


def _detect_title(text: str) -> str:
    line = _first_title_line(text)
    line = URL_PATTERN.sub(" ", line)
    line = SIZE_PATTERN.sub(" ", line)
    line = FORMAT_PATTERN.sub(" ", line)
    line = re.sub(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}", " ", line)
    line = TITLE_NOISE_PATTERN.sub(" ", line)
    line = ARABIC_TITLE_NOISE_PATTERN.sub(" ", line)
    line = re.sub(r"[_|]+", " ", line)
    line = re.sub(r"\s*[-:]+\s*$", " ", line)
    title = " ".join(line.split()).strip(" -_.,:")
    if title:
        return title[:500]
    raise AvailabilityCandidateError("Could not detect a candidate title.")


def _first_title_line(text: str) -> str:
    for line in text.splitlines():
        candidate = line.strip()
        if candidate and not URL_PATTERN.fullmatch(candidate):
            return candidate
    return text


def _normalize_size_bytes(size_bytes: int) -> int:
    try:
        size = int(size_bytes)
    except (TypeError, ValueError):
        return 0
    return max(size, 0)


def _has_duplicate_candidate(
    book: Book, provider: str, title: str, format_guess: str, source_reference: str
) -> bool:
    provider_key = str(provider or "").strip().casefold()
    title_key = " ".join(str(title or "").split()).casefold()
    format_key = normalize_format(format_guess)
    source_key = str(source_reference or "").strip()
    for candidate in book.availability_candidates:
        if (
            candidate.provider == provider_key
            and candidate.title.casefold() == title_key
            and candidate.format_guess == format_key
            and candidate.source_reference == source_key
        ):
            return True
    return False


def _result_value(result: object, name: str):
    if isinstance(result, dict):
        return result.get(name)
    return getattr(result, name, "")
