from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

DEFAULT_NOTION_SCORE_LABELS = (
    "god mode",
    "close to god mode",
    "masterpiece",
    "Sweet",
    "good",
    "acceptable",
    "naah",
    "i don't like it",
)
CANONICAL_SCORE_VALUES = (5.0, 4.5, 4.0, 3.5, 3.0, 2.5, 2.0, 1.5)
LEGACY_SCORE_VALUES = (9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0)


@dataclass(frozen=True, slots=True)
class ScoreOption:
    label: str
    value: float
    legacy_value: float | None = None


def notion_score_options(labels: Sequence[str] | None = None) -> list[ScoreOption]:
    active_labels = [str(label).strip() for label in (labels or DEFAULT_NOTION_SCORE_LABELS) if str(label).strip()]
    if not active_labels:
        active_labels = list(DEFAULT_NOTION_SCORE_LABELS)
    active_labels = active_labels[: len(CANONICAL_SCORE_VALUES)]
    return [
        ScoreOption(
            label=label,
            value=CANONICAL_SCORE_VALUES[index],
            legacy_value=LEGACY_SCORE_VALUES[index] if index < len(LEGACY_SCORE_VALUES) else None,
        )
        for index, label in enumerate(active_labels)
    ]


def score_option_for_input(
    value: object,
    *,
    labels: Sequence[str] | None = None,
    stored_label: object | None = None,
) -> ScoreOption | None:
    if stored_label:
        option = _score_option_for_label(stored_label, labels=labels)
        if option is not None:
            return option
    option = _score_option_for_label(value, labels=labels)
    if option is not None:
        return option
    try:
        numeric = float(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None
    if numeric is None:
        return None
    return score_option_for_value(numeric, labels=labels)


def score_option_for_value(value: float | None, *, labels: Sequence[str] | None = None) -> ScoreOption | None:
    if value is None:
        return None
    for option in notion_score_options(labels):
        if abs(value - option.value) < 0.001:
            return option
        if option.legacy_value is not None and abs(value - option.legacy_value) < 0.001:
            return option
    return None


def _score_option_for_label(value: object, *, labels: Sequence[str] | None = None) -> ScoreOption | None:
    normalized = _normalize_label(value)
    if not normalized:
        return None
    for option in notion_score_options(labels):
        if _normalize_label(option.label) == normalized:
            return option
    return None


def _normalize_label(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()
