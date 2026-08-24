from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from math import ceil

PROGRAMMING_VERSION = "v1"
SHORT_MAX_SECONDS = 75
DISCOVERY_LEVELS = {"low", "balanced", "high"}
PROGRAM_ROLES = ("opener", "update", "deep_dive", "explainer", "discovery", "wind_down")


@dataclass(frozen=True, slots=True)
class ProgrammingRequest:
    duration_minutes: int
    groups: tuple[str, ...] = ()
    avoid_watched: bool = True
    no_shorts: bool = True
    topics: tuple[str, ...] = ()
    formats: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    mood: str = ""
    goal: str = ""
    discovery_level: str = "balanced"
    allow_live: bool = False

    @property
    def duration_seconds(self) -> int:
        return self.duration_minutes * 60

    def as_dict(self) -> dict:
        return {
            "duration_minutes": self.duration_minutes,
            "groups": list(self.groups),
            "avoid_watched": self.avoid_watched,
            "no_shorts": self.no_shorts,
            "topics": list(self.topics),
            "formats": list(self.formats),
            "languages": list(self.languages),
            "mood": self.mood,
            "goal": self.goal,
            "discovery_level": self.discovery_level,
            "allow_live": self.allow_live,
        }


@dataclass(frozen=True, slots=True)
class ProgrammingCandidate:
    candidate_id: str
    source: str
    content_id: str
    title: str
    creator: str
    duration_seconds: int
    published_at: datetime | None
    groups: tuple[str, ...]
    thumbnail_url: str = ""
    watched: bool = False
    favorite: bool = False
    quality_score: int = 0
    available: bool = True
    is_short: bool = False
    content_type: str = "video"
    language: str = ""
    topics: tuple[str, ...] = ()
    story_key: str = ""
    is_live: bool = False
    playback_hint: str = ""


@dataclass(frozen=True, slots=True)
class ProgrammedItem:
    candidate: ProgrammingCandidate
    score: int
    reason: str
    role: str


def normalise_terms(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip()[:160] for value in values if str(value).strip()}))


def parse_intent(text: str, *, default_duration: int = 60) -> ProgrammingRequest:
    """Safe local intent parser. An LLM adapter may replace this boundary, not programming."""
    value = text.strip()
    lowered = value.casefold()
    duration = default_duration
    match = re.search(r"\b(30|60|90|120)\s*(?:m|min|minutes?|دقيقة)?\b", lowered)
    if match:
        duration = int(match.group(1))
    elif re.search(r"(?:hour|ساعة)\s*(?:and a half|ونص)?", lowered):
        duration = 90 if "half" in lowered or "ونص" in lowered else 60
    topics = tuple(
        topic
        for topic, markers in {
            "Science": ("science", "scientific", "علم"),
            "History": ("history", "historical", "تاريخ"),
            "Geopolitics": ("geopolit", "politics", "جيو"),
            "Technology": ("tech", "technology", "تكنولوجيا"),
            "Documentary": ("documentary", "وثائقي"),
        }.items()
        if any(marker in lowered for marker in markers)
    )
    formats = tuple(
        name
        for name, markers in {
            "documentary": ("documentary", "وثائقي"),
            "explainer": ("explainer", "explain", "شرح"),
            "analysis": ("analysis", "تحليل"),
        }.items()
        if any(marker in lowered for marker in markers)
    )
    languages = tuple(
        language
        for language, markers in {
            "ar": ("arabic", "العربية"),
            "en": ("english", "انجليزية"),
        }.items()
        if any(marker in lowered for marker in markers)
    )
    excluded_shorts = any(
        marker in lowered for marker in ("no shorts", "without shorts", "بلا shorts")
    )
    mood = "calm" if any(marker in lowered for marker in ("calm", "quiet", "هادئ", "نرتاح")) else ""
    goal = "learn" if any(marker in lowered for marker in ("learn", "study", "تعلم")) else ""
    return ProgrammingRequest(
        duration_minutes=duration if duration in {30, 60, 90, 120} else default_duration,
        groups=topics,
        topics=topics,
        formats=formats,
        languages=languages,
        no_shorts=excluded_shorts or "shorts" not in lowered,
        mood=mood,
        goal=goal,
    )


def _age_days(value: datetime | None) -> int:
    if value is None:
        return 90
    instant = value if value.tzinfo else value.replace(tzinfo=UTC)
    return max(0, (datetime.now(UTC) - instant).days)


def _terms(candidate: ProgrammingCandidate) -> set[str]:
    return {
        *{term.casefold() for term in candidate.groups},
        *{term.casefold() for term in candidate.topics},
        candidate.content_type.casefold(),
    }


def _base_score(
    candidate: ProgrammingCandidate, request: ProgrammingRequest
) -> tuple[int, list[str]]:
    score = candidate.quality_score
    reasons: list[str] = []
    requested = {term.casefold() for term in (*request.groups, *request.topics)}
    matched = _terms(candidate) & requested
    if matched:
        score += 48
        reasons.append(f"matches {sorted(matched)[0]}")
    elif requested:
        score -= 14
    if request.formats and candidate.content_type.casefold() in {
        value.casefold() for value in request.formats
    }:
        score += 14
        reasons.append(f"is a {candidate.content_type}")
    if candidate.favorite:
        score += 12
        reasons.append("saved in your library")
    if candidate.source == "youtube_watch_later":
        score += 8
        reasons.append("in Watch Later")
    if candidate.is_live:
        score += 10
        reasons.append("live now")
    score += max(0, 12 - min(_age_days(candidate.published_at), 36) // 3)
    return score, reasons


def eligible_candidates(
    candidates: list[ProgrammingCandidate], request: ProgrammingRequest
) -> list[ProgrammingCandidate]:
    language_set = {language.casefold() for language in request.languages}
    format_set = {content_type.casefold() for content_type in request.formats}
    return [
        candidate
        for candidate in candidates
        if candidate.available
        and candidate.duration_seconds > 0
        and (request.allow_live or not candidate.is_live)
        and (not request.avoid_watched or not candidate.watched)
        and (not request.no_shorts or not candidate.is_short)
        and (
            not language_set
            or not candidate.language
            or candidate.language.casefold() in language_set
        )
        and (not format_set or candidate.content_type.casefold() in format_set)
    ]


def _role_for(index: int, total: int, candidate: ProgrammingCandidate) -> str:
    if index == 0:
        return "opener"
    if index == total - 1:
        return "wind_down"
    if candidate.duration_seconds >= 35 * 60:
        return "deep_dive"
    if candidate.is_live:
        return "update"
    return "explainer"


def build_lineup(
    candidates: list[ProgrammingCandidate], request: ProgrammingRequest
) -> list[ProgrammedItem]:
    """Build a deterministic programme with diversity, story dedupe, pacing, and a time budget."""
    pool = eligible_candidates(candidates, request)
    target = request.duration_seconds
    ceiling = target + min(8 * 60, max(3 * 60, target // 8))
    floor = max(12 * 60, int(target * 0.75))
    chosen: list[ProgrammedItem] = []
    creator_counts: dict[str, int] = {}
    story_keys: set[str] = set()
    total = 0

    while pool:
        expected_items = max(2, ceil(target / max(10 * 60, target // 4)))
        creator_limit = max(1, ceil(expected_items / 2))
        ranked: list[tuple[int, ProgrammingCandidate, list[str]]] = []
        for candidate in pool:
            if total + candidate.duration_seconds > ceiling:
                continue
            creator_key = candidate.creator.casefold().strip()
            if creator_key and creator_counts.get(creator_key, 0) >= creator_limit:
                continue
            if (
                len(chosen) >= 2
                and creator_key
                and all(
                    item.candidate.creator.casefold().strip() == creator_key for item in chosen[-2:]
                )
            ):
                continue
            if candidate.story_key and candidate.story_key in story_keys:
                continue
            score, reasons = _base_score(candidate, request)
            remaining_after = max(0, target - (total + candidate.duration_seconds))
            score += max(0, 16 - abs(remaining_after - candidate.duration_seconds) // 90)
            score -= creator_counts.get(creator_key, 0) * 18 if creator_key else 0
            ranked.append((score, candidate, reasons))
        if not ranked:
            break
        score, candidate, reasons = sorted(
            ranked, key=lambda item: (-item[0], item[1].duration_seconds, item[1].candidate_id)
        )[0]
        role = _role_for(len(chosen), expected_items, candidate)
        reason = ", ".join(reasons[:2]) or "fits this session"
        chosen.append(ProgrammedItem(candidate, score, reason, role))
        total += candidate.duration_seconds
        creator_key = candidate.creator.casefold().strip()
        if creator_key:
            creator_counts[creator_key] = creator_counts.get(creator_key, 0) + 1
        if candidate.story_key:
            story_keys.add(candidate.story_key)
        pool.remove(candidate)
        if total >= floor and not any(total + item.duration_seconds <= ceiling for item in pool):
            break

    if not chosen and pool:
        candidate = min(pool, key=lambda item: abs(item.duration_seconds - target))
        score, reasons = _base_score(candidate, request)
        chosen.append(
            ProgrammedItem(
                candidate, score, ", ".join(reasons[:2]) or "best duration fit", "opener"
            )
        )
    return [
        replace(item, role=_role_for(index, len(chosen), item.candidate))
        for index, item in enumerate(chosen)
    ]
