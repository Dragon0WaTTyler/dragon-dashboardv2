from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import func, select

from app.extensions import db
from app.mytv.epg import now_next_for_ids
from app.mytv.models import (
    TVChannel,
    TVChannelPreference,
    TVChannelRepresentative,
    TVGroup,
    TVTheme,
)
from app.personal_tv.programming import SHORT_MAX_SECONDS, ProgrammingCandidate
from app.youtube.grouping import is_archive_group, is_favorite_group, ordered_groups
from app.youtube.models import YouTubeVideo


class CandidateProvider(Protocol):
    """A source adapter exposes normalized candidates, never source credentials or streams."""

    source: str

    @staticmethod
    def candidates() -> list[ProgrammingCandidate]: ...


def _terms(value: str) -> tuple[str, ...]:
    words = re.findall(r"[a-zA-Z]{4,}", value.casefold())
    return tuple(sorted(set(words)))[:12]


def _story_key(value: str) -> str:
    ignored = {"video", "programme", "program", "episode", "official", "watch", "the"}
    terms = [term for term in _terms(value) if term not in ignored]
    return " ".join(terms[:5]) if len(terms) >= 2 else ""


class YouTubeCandidateProvider:
    """Adapter boundary: personal_tv never calls YouTube APIs or owns their cache."""

    source = "youtube"

    @staticmethod
    def candidates() -> list[ProgrammingCandidate]:
        videos = list(
            db.session.scalars(
                db.select(YouTubeVideo).where(YouTubeVideo.removed_from_source.is_(False))
            )
        )
        # A PocketTube membership and Watch Later can point at the same source video.
        chosen: dict[str, YouTubeVideo] = {}
        groups_by_video: dict[str, set[str]] = {}
        for video in videos:
            canonical = video.external_id.split("::pt:", 1)[0]
            if video.source == "pockettube" and video.group_name:
                groups_by_video.setdefault(canonical, set()).add(video.group_name)
            previous = chosen.get(canonical)
            prioritize_watch_later = (
                previous is not None
                and video.source == "watch_later"
                and previous.source != "watch_later"
            )
            if previous is None or prioritize_watch_later:
                chosen[canonical] = video
        return [
            ProgrammingCandidate(
                candidate_id=video.id,
                source="youtube",
                content_id=video.external_id.split("::pt:", 1)[0],
                title=video.title,
                creator=video.channel_title,
                duration_seconds=video.duration_seconds,
                published_at=video.published_at,
                groups=tuple(
                    group
                    for group in sorted(groups_by_video.get(canonical, {video.group_name}))
                    if group and not is_archive_group(group)
                ),
                thumbnail_url=video.thumbnail_url,
                watched=video.watched,
                favorite=any(
                    is_favorite_group(group)
                    for group in groups_by_video.get(canonical, {video.group_name})
                ),
                quality_score=(8 if video.source == "watch_later" else 4)
                + (
                    8
                    if any(
                        is_favorite_group(group)
                        for group in groups_by_video.get(canonical, {video.group_name})
                    )
                    else 0
                ),
                available=not video.removed_from_source,
                is_short=(0 < video.duration_seconds <= SHORT_MAX_SECONDS)
                or "#short" in f"{video.title}\n{video.description}".casefold(),
                content_type="documentary" if "documentary" in video.title.casefold() else "video",
                topics=_terms(f"{video.title} {video.description}"),
                story_key=_story_key(video.title),
            )
            for canonical, video in chosen.items()
            if video.source == "watch_later"
            or any(
                not is_archive_group(group)
                for group in groups_by_video.get(canonical, {video.group_name})
                if group
            )
        ]

    @staticmethod
    def groups() -> list[dict[str, object]]:
        rows = db.session.execute(
            db.select(YouTubeVideo.group_name, func.count())
            .where(
                YouTubeVideo.source == "pockettube",
                YouTubeVideo.group_name != "",
                YouTubeVideo.removed_from_source.is_(False),
            )
            .group_by(YouTubeVideo.group_name)
            .order_by(YouTubeVideo.group_name)
        )
        groups = [
            {
                "name": name,
                "count": int(count),
                "favorite": is_favorite_group(name),
            }
            for name, count in rows
            if not is_archive_group(name)
        ]
        return ordered_groups(groups)


class IPTVCandidateProvider:
    """Read live candidates from IPTV catalogue and EPG; IPTV keeps stream ownership."""

    source = "iptv"

    @staticmethod
    def candidates() -> list[ProgrammingCandidate]:
        effective_enabled = func.coalesce(
            TVChannel.enabled_override, TVTheme.channel_policy, TVTheme.enabled
        ).is_(True)
        rows = list(
            db.session.execute(
                select(TVChannel, TVChannelPreference, TVTheme.name.label("theme_name"))
                .join(
                    TVChannelRepresentative,
                    TVChannelRepresentative.channel_id == TVChannel.id,
                )
                .join(
                    TVChannelPreference,
                    TVChannelPreference.preference_key == TVChannel.preference_key,
                )
                .join(TVGroup, TVGroup.id == TVChannel.group_id)
                .join(TVTheme, TVTheme.id == TVGroup.theme_id)
                .where(TVChannelPreference.favorite.is_(True), effective_enabled)
            )
        )
        guide = now_next_for_ids({channel.tvg_id for channel, _, _ in rows if channel.tvg_id})
        now = datetime.now(timezone.utc)
        candidates: list[ProgrammingCandidate] = []
        for channel, preference, theme_name in rows:
            current = guide.get(channel.tvg_id, {}).get("now")
            if not current:
                continue
            ends_at = datetime.fromisoformat(current["ends_at"])
            duration = max(60, int((ends_at - now).total_seconds()))
            title = current["title"]
            candidates.append(
                ProgrammingCandidate(
                    candidate_id=f"iptv:{channel.id}:{current['starts_at']}",
                    source="iptv",
                    content_id=str(channel.id),
                    title=title,
                    creator=channel.name,
                    duration_seconds=duration,
                    published_at=None,
                    groups=(str(theme_name),),
                    thumbnail_url=channel.logo_url,
                    favorite=preference.favorite,
                    quality_score=18,
                    content_type="live_program",
                    topics=_terms(f"{theme_name} {title}"),
                    story_key=_story_key(title),
                    is_live=True,
                    playback_hint="Open in IPTV",
                )
            )
        return candidates


def candidates_from(providers: tuple[type[CandidateProvider], ...]) -> list[ProgrammingCandidate]:
    candidates: list[ProgrammingCandidate] = []
    for provider in providers:
        candidates.extend(provider.candidates())
    return candidates
