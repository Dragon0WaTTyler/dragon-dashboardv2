from __future__ import annotations

import unicodedata

RTL_BIDI_CLASSES = frozenset({"R", "AL", "AN"})


def text_direction(value: object) -> str:
    text = str(value or "")
    return (
        "rtl"
        if any(unicodedata.bidirectional(character) in RTL_BIDI_CLASSES for character in text)
        else "ltr"
    )
