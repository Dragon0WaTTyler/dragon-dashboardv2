from __future__ import annotations

from uuid import uuid4

DRAGON_BOOK_ID_PREFIX = "dragon-book"


def new_dragon_book_id() -> str:
    return f"{DRAGON_BOOK_ID_PREFIX}-{uuid4().hex}"


def ensure_dragon_book_id(value: str | None) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized else new_dragon_book_id()
