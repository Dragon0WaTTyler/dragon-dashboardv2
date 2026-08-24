from dataclasses import replace
from datetime import UTC, datetime

from app.personal_tv.programming import ProgrammingCandidate, ProgrammingRequest, build_lineup


def candidate(key, minutes, creator, group="Science", watched=False, short=False):
    return ProgrammingCandidate(
        candidate_id=key,
        source="youtube",
        content_id=key,
        title=key,
        creator=creator,
        duration_seconds=minutes * 60,
        published_at=datetime(2026, 8, 20, tzinfo=UTC),
        groups=(group,),
        watched=watched,
        is_short=short,
    )


def test_v0_programming_filters_and_prevents_three_consecutive_creator():
    result = build_lineup(
        [
            candidate("one", 22, "A"),
            candidate("two", 20, "A"),
            candidate("three", 18, "A"),
            candidate("four", 24, "B"),
            candidate("watched", 12, "C", watched=True),
            candidate("short", 1, "D", short=True),
        ],
        ProgrammingRequest(60, ("Science",), avoid_watched=True, no_shorts=True),
    )
    ids = [item.candidate.candidate_id for item in result]
    assert "watched" not in ids and "short" not in ids
    assert all(
        not (
            result[index].candidate.creator
            == result[index + 1].candidate.creator
            == result[index + 2].candidate.creator
        )
        for index in range(max(0, len(result) - 2))
    )
    assert sum(item.candidate.duration_seconds for item in result) <= 68 * 60


def test_programming_accepts_live_only_when_requested_and_deduplicates_stories():
    live = ProgrammingCandidate(
        candidate_id="iptv:42",
        source="iptv",
        content_id="42",
        title="A live science briefing",
        creator="Dragon News",
        duration_seconds=25 * 60,
        published_at=None,
        groups=("Science",),
        is_live=True,
        content_type="live_program",
        story_key="science briefing",
    )
    duplicate_story = ProgrammingCandidate(
        candidate_id="youtube:briefing",
        source="youtube",
        content_id="briefing",
        title="The same science briefing",
        creator="Other source",
        duration_seconds=20 * 60,
        published_at=datetime(2026, 8, 20, tzinfo=UTC),
        groups=("Science",),
        story_key="science briefing",
    )
    blocked = build_lineup([live], ProgrammingRequest(30, ("Science",)))
    assert blocked == []
    allowed = build_lineup([live], ProgrammingRequest(30, ("Science",), allow_live=True))
    assert allowed[0].candidate.source == "iptv"
    deduped = build_lineup(
        [duplicate_story, replace(duplicate_story, candidate_id="youtube:other")],
        ProgrammingRequest(60, ("Science",)),
    )
    assert len(deduped) == 1
