from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select

from app.extensions import db
from app.personal_tv.models import (
    PersonalTVFeedback,
    PreparedTVProgram,
    ProgrammingPreferences,
    TVSession,
    TVSessionItem,
)
from app.personal_tv.programming import (
    DISCOVERY_LEVELS,
    PROGRAMMING_VERSION,
    ProgrammedItem,
    ProgrammingCandidate,
    ProgrammingRequest,
    build_lineup,
    normalise_terms,
)
from app.personal_tv.providers import (
    IPTVCandidateProvider,
    YouTubeCandidateProvider,
    candidates_from,
)
from app.shared.time import utc_iso, utc_now
from app.youtube.models import YouTubeVideo

ACTIVE_STATES = ("planned", "playing", "paused")
SESSION_TTL = timedelta(hours=12)
DEFAULT_DAYPART_PROFILES = {
    "morning": {"start": "07:30", "duration_minutes": 30, "name": "Morning Brief"},
    "evening": {"start": "19:00", "duration_minutes": 90, "name": "Evening TV"},
    "wind_down": {"start": "22:30", "duration_minutes": 60, "name": "Wind Down"},
}


class PersonalTVService:
    @staticmethod
    def preferences() -> ProgrammingPreferences:
        record = db.session.get(ProgrammingPreferences, 1)
        if record is None:
            record = ProgrammingPreferences(id=1, daypart_profiles=DEFAULT_DAYPART_PROFILES)
            db.session.add(record)
            db.session.flush()
        return record

    @staticmethod
    def preferences_payload(preferences: ProgrammingPreferences | None = None) -> dict:
        preferences = preferences or PersonalTVService.preferences()
        return {
            "default_duration_minutes": preferences.default_duration_minutes,
            "selected_groups": preferences.selected_groups,
            "avoid_watched": preferences.avoid_watched,
            "no_shorts": preferences.no_shorts,
            "preferred_topics": preferences.preferred_topics,
            "preferred_formats": preferences.preferred_formats,
            "preferred_languages": preferences.preferred_languages,
            "preferred_creators": preferences.preferred_creators,
            "blocked_creators": preferences.blocked_creators,
            "avoided_keywords": preferences.avoided_keywords,
            "discovery_level": preferences.discovery_level,
            "source_quality": preferences.source_quality,
            "daypart_profiles": preferences.daypart_profiles,
            "enabled": preferences.enabled,
        }

    @staticmethod
    def update_preferences(payload: dict) -> ProgrammingPreferences:
        preferences = PersonalTVService.preferences()
        text_lists = {
            "preferred_topics",
            "preferred_formats",
            "preferred_languages",
            "preferred_creators",
            "blocked_creators",
            "avoided_keywords",
            "selected_groups",
        }
        for field in text_lists:
            if field in payload:
                value = payload[field]
                if not isinstance(value, list):
                    raise ValueError(f"{field} must be a list.")
                setattr(preferences, field, list(normalise_terms(value)))
        for field in ("avoid_watched", "no_shorts", "enabled"):
            if field in payload:
                setattr(preferences, field, bool(payload[field]))
        if "default_duration_minutes" in payload:
            duration = int(payload["default_duration_minutes"])
            if duration not in {30, 60, 90, 120}:
                raise ValueError("Choose 30, 60, 90, or 120 minutes.")
            preferences.default_duration_minutes = duration
        if "discovery_level" in payload:
            discovery = str(payload["discovery_level"]).casefold()
            if discovery not in DISCOVERY_LEVELS:
                raise ValueError("Discovery must be low, balanced, or high.")
            preferences.discovery_level = discovery
        if "daypart_profiles" in payload:
            profiles = payload["daypart_profiles"]
            if not isinstance(profiles, dict):
                raise ValueError("Daypart profiles must be an object.")
            preferences.daypart_profiles = {
                key: value
                for key, value in profiles.items()
                if key in {"morning", "evening", "wind_down"}
            }
        if "source_quality" in payload:
            source_quality = payload["source_quality"]
            if not isinstance(source_quality, dict):
                raise ValueError("Source quality must be an object.")
            cleaned: dict[str, int] = {}
            for source, weight in source_quality.items():
                if source not in {"youtube", "iptv"}:
                    continue
                numeric = int(weight)
                if not -50 <= numeric <= 50:
                    raise ValueError("Source quality weights must be between -50 and 50.")
                cleaned[source] = numeric
            preferences.source_quality = cleaned
        db.session.commit()
        return preferences

    @staticmethod
    def _expire_stale_sessions() -> None:
        cutoff = utc_now()
        stale = list(
            db.session.scalars(
                select(TVSession).where(
                    TVSession.state.in_(ACTIVE_STATES),
                    TVSession.expires_at.is_not(None),
                    TVSession.expires_at < cutoff,
                )
            )
        )
        for session in stale:
            session.state = "abandoned"
            session.ending_reason = "expired"
            session.completed_at = cutoff
        if stale:
            db.session.commit()

    @staticmethod
    def active_session() -> TVSession | None:
        PersonalTVService._expire_stale_sessions()
        return db.session.scalar(
            select(TVSession)
            .where(TVSession.state.in_(ACTIVE_STATES))
            .order_by(TVSession.updated_at.desc())
        )

    @staticmethod
    def _request_with_preferences(request: ProgrammingRequest) -> ProgrammingRequest:
        preferences = PersonalTVService.preferences()
        return replace(
            request,
            topics=normalise_terms((*preferences.preferred_topics, *request.topics)),
            formats=normalise_terms((*preferences.preferred_formats, *request.formats)),
            languages=normalise_terms((*preferences.preferred_languages, *request.languages)),
            discovery_level=request.discovery_level
            if request.discovery_level in DISCOVERY_LEVELS
            else preferences.discovery_level,
        )

    @staticmethod
    def _candidate_pool(request: ProgrammingRequest) -> list[ProgrammingCandidate]:
        providers = (
            (YouTubeCandidateProvider, IPTVCandidateProvider)
            if request.allow_live
            else (YouTubeCandidateProvider,)
        )
        preferences = PersonalTVService.preferences()
        blocked = {value.casefold() for value in preferences.blocked_creators}
        preferred = {value.casefold() for value in preferences.preferred_creators}
        avoided = {value.casefold() for value in preferences.avoided_keywords}
        candidates: list[ProgrammingCandidate] = []
        for candidate in candidates_from(providers):
            searchable = f"{candidate.title} {' '.join(candidate.topics)}".casefold()
            if candidate.creator.casefold() in blocked or any(
                word in searchable for word in avoided
            ):
                continue
            boost = 20 if candidate.creator.casefold() in preferred else 0
            boost += int(preferences.source_quality.get(candidate.source, 0))
            candidates.append(replace(candidate, quality_score=candidate.quality_score + boost))
        return candidates

    @staticmethod
    def _append_programmed_item(
        session: TVSession, programmed: ProgrammedItem, position: int
    ) -> TVSessionItem:
        candidate = programmed.candidate
        item = TVSessionItem(
            position=position,
            source=candidate.source,
            candidate_id=candidate.candidate_id,
            content_id=candidate.content_id,
            title=candidate.title,
            creator=candidate.creator,
            thumbnail_url=candidate.thumbnail_url,
            duration_seconds=candidate.duration_seconds,
            planned_duration_seconds=candidate.duration_seconds,
            reason_selected=programmed.reason,
            content_type=candidate.content_type,
            language=candidate.language,
            program_role=programmed.role,
            story_key=candidate.story_key,
        )
        session.items.append(item)
        return item

    @staticmethod
    def create_session(request: ProgrammingRequest) -> TVSession:
        request = PersonalTVService._request_with_preferences(request)
        preferences = PersonalTVService.preferences()
        preferences.default_duration_minutes = request.duration_minutes
        preferences.selected_groups = list(request.groups)
        preferences.avoid_watched = request.avoid_watched
        preferences.no_shorts = request.no_shorts

        active = PersonalTVService.active_session()
        if active is not None:
            active.state = "abandoned"
            active.ending_reason = "replaced_by_new_session"
            active.completed_at = utc_now()

        lineup = build_lineup(PersonalTVService._candidate_pool(request), request)
        now = utc_now()
        session = TVSession(
            requested_duration_seconds=request.duration_seconds,
            request_groups=list(request.groups),
            avoid_watched=request.avoid_watched,
            no_shorts=request.no_shorts,
            request_intent=request.as_dict(),
            programming_version=PROGRAMMING_VERSION,
            expires_at=now + SESSION_TTL,
        )
        for position, programmed in enumerate(lineup):
            PersonalTVService._append_programmed_item(session, programmed, position)
        db.session.add(session)
        db.session.commit()
        return session

    @staticmethod
    def _visible_items(session: TVSession) -> list[TVSessionItem]:
        hidden_states = {"unavailable", "replaced"}
        return sorted(
            (item for item in session.items if item.state not in hidden_states),
            key=lambda item: (item.position, item.id or 0),
        )

    @staticmethod
    def _current_item(session: TVSession) -> TVSessionItem | None:
        items = PersonalTVService._visible_items(session)
        if not items:
            return None
        session.current_item_index = min(session.current_item_index, len(items) - 1)
        return items[session.current_item_index]

    @staticmethod
    def session_payload(session: TVSession | None) -> dict | None:
        if session is None:
            return None
        items = PersonalTVService._visible_items(session)
        total = sum(
            item.planned_duration_seconds for item in items if item.state not in {"skipped"}
        )
        return {
            "id": session.id,
            "state": session.state,
            "ending_reason": session.ending_reason,
            "requested_duration_seconds": session.requested_duration_seconds,
            "planned_duration_seconds": total,
            "request_groups": session.request_groups,
            "request_intent": session.request_intent,
            "current_item_index": session.current_item_index,
            "elapsed_seconds": session.elapsed_seconds,
            "expires_at": utc_iso(session.expires_at) if session.expires_at else None,
            "items": [
                {
                    "id": item.id,
                    "position": item.position,
                    "source": item.source,
                    "candidate_id": item.candidate_id,
                    "content_id": item.content_id,
                    "title": item.title,
                    "creator": item.creator,
                    "thumbnail_url": item.thumbnail_url,
                    "duration_seconds": item.duration_seconds,
                    "state": item.state,
                    "completion_ratio": item.completion_ratio,
                    "reason_selected": item.reason_selected,
                    "skip_reason": item.skip_reason,
                    "content_type": item.content_type,
                    "program_role": item.program_role,
                    "playback_hint": "Open in IPTV" if item.source == "iptv" else "",
                }
                for item in items
            ],
        }

    @staticmethod
    def _feedback(session: TVSession, item: TVSessionItem, kind: str, reason: str = "") -> None:
        db.session.add(
            PersonalTVFeedback(
                session_id=session.id,
                session_item_id=item.id,
                candidate_id=item.candidate_id,
                creator=item.creator,
                kind=kind,
                reason=reason[:100],
            )
        )

    @staticmethod
    def _mark_watched(item: TVSessionItem) -> None:
        if item.source != "youtube":
            return
        _, separator, video_id = item.candidate_id.partition(":")
        if not separator:
            video_id = item.candidate_id
        video = db.session.get(YouTubeVideo, video_id)
        if video is not None:
            video.watched = True
            video.local_history = [
                *video.local_history,
                {"event": "completed_in_personal_tv", "at": utc_iso()},
            ]

    @staticmethod
    def transition(session: TVSession, action: str, skip_reason: str = "") -> TVSession:
        now = utc_now()
        current = PersonalTVService._current_item(session)
        if action == "play":
            session.state = "playing"
            session.started_at = session.started_at or now
            if current:
                current.state = "playing"
                current.started_at = current.started_at or now
        elif action == "pause" and session.state == "playing":
            session.state = "paused"
        elif action in {"skip", "complete_item"} and current:
            current.state = "skipped" if action == "skip" else "completed"
            current.skip_reason = skip_reason[:100] if action == "skip" else ""
            current.completion_ratio = (
                100 if action == "complete_item" else current.completion_ratio
            )
            current.completed_at = now
            if action == "complete_item":
                PersonalTVService._mark_watched(current)
                PersonalTVService._feedback(session, current, "completed")
            else:
                PersonalTVService._feedback(session, current, "skipped", skip_reason)
            session.elapsed_seconds += current.duration_seconds
            visible = PersonalTVService._visible_items(session)
            if session.current_item_index + 1 >= len(visible):
                session.state = "completed"
                session.ending_reason = "finished"
                session.completed_at = now
            else:
                session.current_item_index += 1
                session.state = "playing"
                next_item = PersonalTVService._current_item(session)
                if next_item:
                    next_item.state = "playing"
                    next_item.started_at = next_item.started_at or now
        elif action == "stop":
            session.state = "abandoned"
            session.ending_reason = "stopped_by_viewer"
            session.completed_at = now
        else:
            raise ValueError("Unsupported session transition.")
        db.session.commit()
        return session

    @staticmethod
    def record_progress(session: TVSession, completion_ratio: int) -> TVSession:
        item = PersonalTVService._current_item(session)
        if item is None:
            return session
        item.completion_ratio = max(0, min(99, completion_ratio))
        db.session.commit()
        return session

    @staticmethod
    def _request_from_session(session: TVSession) -> ProgrammingRequest:
        payload = session.request_intent or {}
        return ProgrammingRequest(
            duration_minutes=max(30, min(120, int(payload.get("duration_minutes", 60)))),
            groups=normalise_terms(payload.get("groups", session.request_groups)),
            avoid_watched=bool(payload.get("avoid_watched", session.avoid_watched)),
            no_shorts=bool(payload.get("no_shorts", session.no_shorts)),
            topics=normalise_terms(payload.get("topics", [])),
            formats=normalise_terms(payload.get("formats", [])),
            languages=normalise_terms(payload.get("languages", [])),
            mood=str(payload.get("mood", ""))[:80],
            goal=str(payload.get("goal", ""))[:80],
            discovery_level=str(payload.get("discovery_level", "balanced")),
            allow_live=bool(payload.get("allow_live", False)),
        )

    @staticmethod
    def replace_current_item(session: TVSession, reason: str = "unavailable") -> TVSession:
        current = PersonalTVService._current_item(session)
        if current is None:
            raise ValueError("This session has no item to replace.")
        request = PersonalTVService._request_from_session(session)
        known = {item.candidate_id for item in session.items}
        lineup = build_lineup(
            [
                candidate
                for candidate in PersonalTVService._candidate_pool(request)
                if candidate.candidate_id not in known
            ],
            replace(
                request,
                duration_minutes=max(
                    30, min(120, round(current.duration_seconds / 60 / 30) * 30 or 30)
                ),
            ),
        )
        if not lineup:
            raise ValueError("No equivalent replacement is available right now.")
        old_position = current.position
        current.state = "unavailable"
        current.completed_at = utc_now()
        current.skip_reason = reason[:100]
        current.position = max((item.position for item in session.items), default=0) + 1
        PersonalTVService._feedback(session, current, "unavailable", reason)
        replacement = PersonalTVService._append_programmed_item(session, lineup[0], old_position)
        replacement.state = "playing" if session.state == "playing" else "queued"
        replacement.started_at = utc_now() if session.state == "playing" else None
        db.session.commit()
        return session

    @staticmethod
    def regenerate_remainder(session: TVSession) -> TVSession:
        current = PersonalTVService._current_item(session)
        if current is None:
            raise ValueError("This session has no remaining programme.")
        visible = PersonalTVService._visible_items(session)
        start = session.current_item_index + (1 if current.state == "playing" else 0)
        retired = visible[start:]
        remaining_seconds = sum(item.duration_seconds for item in retired)
        if remaining_seconds < 5 * 60:
            raise ValueError("There is not enough remaining time to regenerate.")
        for item in retired:
            item.state = "replaced"
            item.position = max(existing.position for existing in session.items) + 1
        request = PersonalTVService._request_from_session(session)
        request = replace(
            request, duration_minutes=max(30, min(120, round(remaining_seconds / 60 / 30) * 30))
        )
        known = {item.candidate_id for item in session.items}
        lineup = build_lineup(
            [
                candidate
                for candidate in PersonalTVService._candidate_pool(request)
                if candidate.candidate_id not in known
            ],
            request,
        )
        if not lineup:
            raise ValueError("No new programme matches the remaining session.")
        position = start
        for programmed in lineup:
            PersonalTVService._append_programmed_item(session, programmed, position)
            position += 1
        db.session.commit()
        return session

    @staticmethod
    def submit_feedback(session: TVSession, kind: str, reason: str = "") -> TVSession:
        if kind not in {"more_like_this", "less_like_this", "not_interested", "hide_channel"}:
            raise ValueError("Unsupported feedback.")
        item = PersonalTVService._current_item(session)
        if item is None:
            raise ValueError("There is no programme to rate.")
        PersonalTVService._feedback(session, item, kind, reason)
        preferences = PersonalTVService.preferences()
        creator = item.creator.strip()
        if kind == "more_like_this" and creator:
            preferences.preferred_creators = list(
                normalise_terms([*preferences.preferred_creators, creator])
            )
        elif kind == "hide_channel" and creator:
            preferences.blocked_creators = list(
                normalise_terms([*preferences.blocked_creators, creator])
            )
        elif kind == "not_interested" and item.content_type:
            preferences.avoided_keywords = list(
                normalise_terms([*preferences.avoided_keywords, item.content_type])
            )
        db.session.commit()
        return session

    @staticmethod
    def viewer_profile_payload() -> dict:
        feedback = list(
            db.session.scalars(
                select(PersonalTVFeedback).order_by(PersonalTVFeedback.created_at.desc()).limit(300)
            )
        )
        completed = [entry for entry in feedback if entry.kind == "completed"]
        skipped = [entry for entry in feedback if entry.kind == "skipped"]
        return {
            "explicit": PersonalTVService.preferences_payload(),
            "observed": {
                "completed_programmes": len(completed),
                "skipped_programmes": len(skipped),
                "most_finished_creators": _top_values(entry.creator for entry in completed),
                "most_skipped_creators": _top_values(entry.creator for entry in skipped),
            },
        }

    @staticmethod
    def semantic_state() -> dict:
        """Only durable, user-meaningful My TV state belongs in a future sync payload."""
        feedback = list(
            db.session.scalars(
                select(PersonalTVFeedback).order_by(PersonalTVFeedback.created_at.desc()).limit(500)
            )
        )
        return {
            "version": 1,
            "preferences": PersonalTVService.preferences_payload(),
            "feedback": [
                {
                    "candidate_id": item.candidate_id,
                    "creator": item.creator,
                    "kind": item.kind,
                    "reason": item.reason,
                    "created_at": utc_iso(item.created_at),
                }
                for item in feedback
            ],
        }

    @staticmethod
    def merge_semantic_state(payload: dict) -> dict:
        """Merge preferences and explicit feedback; sessions and playback stay local."""
        preferences = payload.get("preferences", {})
        if not isinstance(preferences, dict):
            raise ValueError("Sync preferences must be an object.")
        PersonalTVService.update_preferences(preferences)
        feedback = payload.get("feedback", [])
        if not isinstance(feedback, list):
            raise ValueError("Sync feedback must be a list.")
        known = {
            (item.candidate_id, item.kind, item.reason)
            for item in db.session.scalars(select(PersonalTVFeedback).limit(1000))
        }
        for item in feedback[:500]:
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("candidate_id", ""))[:80]
            kind = str(item.get("kind", ""))[:40]
            reason = str(item.get("reason", ""))[:100]
            key = (candidate_id, kind, reason)
            if not candidate_id or key in known:
                continue
            db.session.add(
                PersonalTVFeedback(
                    candidate_id=candidate_id,
                    creator=str(item.get("creator", ""))[:240],
                    kind=kind,
                    reason=reason,
                )
            )
            known.add(key)
        db.session.commit()
        return PersonalTVService.semantic_state()

    @staticmethod
    def prepare_program(name: str, starts_at, request: ProgrammingRequest) -> PreparedTVProgram:
        program = PreparedTVProgram(
            name=name.strip()[:120] or "My TV",
            starts_at=starts_at,
            request_payload=request.as_dict(),
        )
        db.session.add(program)
        db.session.commit()
        return program

    @staticmethod
    def generate_daypart_programs(now: datetime | None = None) -> list[dict]:
        """Prepare today's configurable channel without starting playback."""
        current = now or utc_now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        profiles = PersonalTVService.preferences().daypart_profiles or DEFAULT_DAYPART_PROFILES
        created: list[PreparedTVProgram] = []
        for key, profile in profiles.items():
            if key not in DEFAULT_DAYPART_PROFILES or not isinstance(profile, dict):
                continue
            try:
                hour, minute = (int(value) for value in str(profile.get("start", "")).split(":", 1))
                starts_at = datetime.combine(current.date(), time(hour, minute), tzinfo=UTC)
                duration = int(profile.get("duration_minutes", 60))
            except (TypeError, ValueError):
                continue
            if duration not in {30, 60, 90, 120} or starts_at < current - timedelta(hours=2):
                continue
            exists = db.session.scalar(
                select(PreparedTVProgram.id).where(
                    PreparedTVProgram.name == str(profile.get("name", key))[:120],
                    PreparedTVProgram.starts_at == starts_at,
                    PreparedTVProgram.state == "prepared",
                )
            )
            if exists:
                continue
            request = ProgrammingRequest(
                duration_minutes=duration,
                groups=normalise_terms(profile.get("groups", [])),
                topics=normalise_terms(profile.get("topics", [])),
                avoid_watched=bool(profile.get("avoid_watched", True)),
                no_shorts=bool(profile.get("no_shorts", True)),
                allow_live=bool(profile.get("allow_live", False)),
            )
            created.append(
                PreparedTVProgram(
                    name=str(profile.get("name", key))[:120],
                    starts_at=starts_at,
                    request_payload=request.as_dict(),
                )
            )
        if created:
            db.session.add_all(created)
            db.session.commit()
        return PersonalTVService.prepared_programs()

    @staticmethod
    def prepared_programs() -> list[dict]:
        return [
            {
                "id": program.id,
                "name": program.name,
                "starts_at": utc_iso(program.starts_at),
                "state": program.state,
                "request": program.request_payload,
            }
            for program in db.session.scalars(
                select(PreparedTVProgram)
                .where(PreparedTVProgram.state == "prepared")
                .order_by(PreparedTVProgram.starts_at)
                .limit(12)
            )
        ]

    @staticmethod
    def start_prepared_program(program: PreparedTVProgram) -> TVSession:
        if program.state != "prepared":
            raise ValueError("This programme is no longer available.")
        request = ProgrammingRequest(
            duration_minutes=int(program.request_payload.get("duration_minutes", 60)),
            groups=normalise_terms(program.request_payload.get("groups", [])),
            avoid_watched=bool(program.request_payload.get("avoid_watched", True)),
            no_shorts=bool(program.request_payload.get("no_shorts", True)),
            topics=normalise_terms(program.request_payload.get("topics", [])),
            formats=normalise_terms(program.request_payload.get("formats", [])),
            languages=normalise_terms(program.request_payload.get("languages", [])),
            mood=str(program.request_payload.get("mood", "")),
            goal=str(program.request_payload.get("goal", "")),
            discovery_level=str(program.request_payload.get("discovery_level", "balanced")),
            allow_live=bool(program.request_payload.get("allow_live", False)),
        )
        session = PersonalTVService.create_session(request)
        program.state = "started"
        program.session_id = session.id
        db.session.commit()
        return session


def _top_values(values) -> list[dict]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value).strip()
        if key:
            counts[key] = counts.get(key, 0) + 1
    return [
        {"name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]
    ]
