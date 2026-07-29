from __future__ import annotations

LEGACY_BOOK_STATUS_ALIASES = {
    "want_to_read": "wishlist",
}

CANONICAL_BOOK_STATUSES = (
    "wishlist",
    "reading",
    "finished",
    "paused",
    "dropped",
    "reference",
)

ALL_BOOK_STATUSES = {*CANONICAL_BOOK_STATUSES, *LEGACY_BOOK_STATUS_ALIASES}


def normalize_book_status(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    if not normalized:
        return ""
    return LEGACY_BOOK_STATUS_ALIASES.get(normalized, normalized)


def status_filter_values(value: str) -> set[str]:
    normalized = normalize_book_status(value)
    if not normalized:
        return set()
    if normalized == "wishlist":
        return {"wishlist", "want_to_read"}
    return {normalized}
