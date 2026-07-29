from __future__ import annotations

TEXT_FORMAT_PRIORITY = ("KFX", "AZW3", "EPUB", "PDF")
AUDIO_FORMATS = ("M4B", "MP3", "AAC")


def normalize_format(value: str | None) -> str:
    return str(value or "").strip().upper()


def sort_text_formats(values: list[str] | tuple[str, ...]) -> list[str]:
    order = {name: index for index, name in enumerate(TEXT_FORMAT_PRIORITY)}
    normalized = {normalize_format(value) for value in values}
    supported = [value for value in normalized if value in order]
    return sorted(supported, key=lambda value: order[value])


def preferred_text_format(values: list[str] | tuple[str, ...]) -> str:
    ordered = sort_text_formats(values)
    return ordered[0] if ordered else ""


def text_format_slots(values: list[str] | tuple[str, ...]) -> list[dict[str, object]]:
    available = set(sort_text_formats(values))
    return [{"format": name, "available": name in available} for name in TEXT_FORMAT_PRIORITY]
