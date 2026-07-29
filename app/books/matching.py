from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

ISBN_NOISE = re.compile(r"[\s-]+")
TITLE_NOISE = re.compile(
    r"\b(pdf|epub|kfx|azw3|kindle edition|نسخة كاملة|تحميل كتاب)\b",
    re.IGNORECASE,
)
PUNCTUATION = re.compile(r"[^\w\s\u0600-\u06FF]+", re.UNICODE)


def normalize_arabic(value: str) -> str:
    result = str(value or "")
    result = result.replace("ـ", "")
    result = re.sub("[إأآٱ]", "ا", result)
    result = result.replace("ى", "ي")
    return result


def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", normalize_arabic(value)).casefold()
    text = TITLE_NOISE.sub(" ", text)
    text = PUNCTUATION.sub(" ", text)
    return " ".join(text.split())


def normalize_isbn(value: str | None) -> str:
    text = ISBN_NOISE.sub("", str(value or "").strip().upper())
    return text if re.fullmatch(r"[0-9X]{10}|[0-9]{13}", text) else ""


def valid_isbn10(value: str | None) -> bool:
    isbn = normalize_isbn(value)
    if not re.fullmatch(r"[0-9]{9}[0-9X]", isbn):
        return False
    total = 0
    for index, char in enumerate(isbn, start=1):
        digit = 10 if char == "X" else int(char)
        total += index * digit
    return total % 11 == 0


def valid_isbn13(value: str | None) -> bool:
    isbn = normalize_isbn(value)
    if not re.fullmatch(r"[0-9]{13}", isbn):
        return False
    total = sum((1 if index % 2 == 0 else 3) * int(char) for index, char in enumerate(isbn))
    return total % 10 == 0


def split_isbns(values: list[str] | tuple[str, ...] | set[str]) -> tuple[str, str]:
    isbn_10 = ""
    isbn_13 = ""
    for value in values:
        normalized = normalize_isbn(value)
        if not isbn_13 and valid_isbn13(normalized):
            isbn_13 = normalized
        elif not isbn_10 and valid_isbn10(normalized):
            isbn_10 = normalized
    return isbn_10, isbn_13


def title_similarity(left: str, right: str) -> float:
    normalized_left = normalize_title(left)
    normalized_right = normalize_title(right)
    if not normalized_left or not normalized_right:
        return 0.0
    return SequenceMatcher(None, normalized_left, normalized_right).ratio()
