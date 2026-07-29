from __future__ import annotations

from app.books.models import AudiobookEdition, Book
from app.extensions import db

ALLOWED_ABRIDGEMENT_TYPES = {"unabridged", "abridged", "unknown"}
ALLOWED_PRODUCTION_TYPES = {"single_narrator", "multi_narrator", "dramatized"}
ALLOWED_AUDIOBOOK_REVIEW_STATES = {"needs_review", "verified", "rejected"}


class AudiobookCandidateError(ValueError):
    pass


class BookAudiobookService:
    @staticmethod
    def add_candidate(
        book: Book,
        *,
        title: str,
        language: str = "",
        narrator: str = "",
        publisher: str = "",
        release_year: str | int | None = None,
        duration_minutes: str | int | None = None,
        chapter_count: str | int | None = None,
        abridgement_type: str = "unknown",
        production_type: str = "single_narrator",
    ) -> AudiobookEdition:
        normalized_title = " ".join(str(title or book.title or "").split())
        if not normalized_title:
            raise AudiobookCandidateError("Audiobook title is required.")
        normalized_abridgement = _choice(
            abridgement_type,
            allowed=ALLOWED_ABRIDGEMENT_TYPES,
            fallback="unknown",
        )
        normalized_production = _choice(
            production_type,
            allowed=ALLOWED_PRODUCTION_TYPES,
            fallback="single_narrator",
        )
        if _duplicate_candidate(
            book,
            title=normalized_title,
            language=language,
            narrator=narrator,
            publisher=publisher,
        ):
            raise AudiobookCandidateError("This audiobook candidate already exists.")
        audiobook = AudiobookEdition(
            book=book,
            title=normalized_title,
            language=" ".join(str(language or "").split()),
            narrator=" ".join(str(narrator or "").split()),
            publisher=" ".join(str(publisher or "").split()),
            release_year=_optional_int(release_year),
            duration_seconds=_minutes_to_seconds(duration_minutes),
            chapter_count=_optional_int(chapter_count) or 0,
            abridgement_type=normalized_abridgement,
            production_type=normalized_production,
            verification_status="needs_review",
        )
        db.session.add(audiobook)
        db.session.commit()
        return audiobook

    @staticmethod
    def set_review_state(
        book: Book, *, audiobook_id: str, review_state: str
    ) -> AudiobookEdition:
        normalized_state = str(review_state or "").strip().casefold()
        if normalized_state not in ALLOWED_AUDIOBOOK_REVIEW_STATES:
            raise AudiobookCandidateError("Unknown audiobook review state.")
        audiobook = _audiobook_for_book(book, audiobook_id)
        if audiobook.assets and normalized_state == "rejected":
            raise AudiobookCandidateError(
                "Audiobook editions with registered assets cannot be rejected here."
            )
        audiobook.verification_status = normalized_state
        db.session.commit()
        return audiobook


def _audiobook_for_book(book: Book, audiobook_id: str) -> AudiobookEdition:
    for audiobook in book.audiobooks:
        if audiobook.id == audiobook_id:
            return audiobook
    raise AudiobookCandidateError("Audiobook candidate was not found for this book.")


def _duplicate_candidate(
    book: Book, *, title: str, language: str, narrator: str, publisher: str
) -> bool:
    title_key = _key(title)
    language_key = _key(language)
    narrator_key = _key(narrator)
    publisher_key = _key(publisher)
    for audiobook in book.audiobooks:
        if (
            _key(audiobook.title) == title_key
            and _key(audiobook.language) == language_key
            and _key(audiobook.narrator) == narrator_key
            and _key(audiobook.publisher) == publisher_key
        ):
            return True
    return False


def _choice(value: str, *, allowed: set[str], fallback: str) -> str:
    normalized = str(value or "").strip().casefold()
    return normalized if normalized in allowed else fallback


def _optional_int(value: str | int | None) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except (TypeError, ValueError) as exc:
        raise AudiobookCandidateError("Audiobook numeric fields must be whole numbers.") from exc
    if parsed < 0:
        raise AudiobookCandidateError("Audiobook numeric fields cannot be negative.")
    return parsed


def _minutes_to_seconds(value: str | int | None) -> int:
    minutes = _optional_int(value)
    return (minutes or 0) * 60


def _key(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()
