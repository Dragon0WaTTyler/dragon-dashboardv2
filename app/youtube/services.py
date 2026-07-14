from __future__ import annotations

import random

from app.extensions import db
from app.history.services import HistoryService
from app.shared.time import utc_iso
from app.youtube.models import YouTubeVideo
from app.youtube.repositories import YouTubeRepository

SOURCES = {"watch_later", "pockettube"}
ORDERS = {"normal", "shuffle", "shuffle_video"}


def video_item(video: YouTubeVideo) -> dict:
    return {
        "id": video.id,
        "external_id": video.external_id,
        "title": video.title,
        "channel_title": video.channel_title,
        "source": video.source,
        "group_name": video.group_name,
        "thumbnail_url": video.thumbnail_url,
        "published_at": video.published_at.isoformat() if video.published_at else None,
        "duration_seconds": video.duration_seconds,
        "watched": video.watched,
        "removed_from_source": video.removed_from_source,
    }


def video_detail(video: YouTubeVideo) -> dict:
    return {**video_item(video), "description": video.description, "history": video.local_history}


class YouTubeService:
    @staticmethod
    def feed(*, source: str, group: str = "", q: str = "", order: str = "normal") -> dict:
        if source not in SOURCES:
            raise ValueError("Unknown YouTube source.")
        if order not in ORDERS:
            raise ValueError("Unknown order.")
        videos, total = YouTubeRepository.list(source=source, group=group, q=q)
        if order in {"shuffle", "shuffle_video"}:
            random.SystemRandom().shuffle(videos)
            if order == "shuffle_video":
                videos = videos[:1]
        return {"items": [video_item(video) for video in videos], "total": total}

    @staticmethod
    def latest_watch_later(limit: int = 4) -> list[dict]:
        videos, _ = YouTubeRepository.list(source="watch_later", limit=limit)
        return [video_item(video) for video in videos]

    @staticmethod
    def set_watched(video: YouTubeVideo, watched: bool) -> None:
        video.watched = watched
        video.local_history = [*video.local_history, {"event": "watched", "at": utc_iso()}]
        HistoryService.record(
            domain="youtube",
            entity_type="video",
            entity_id=video.id,
            event_type="watched" if watched else "unwatched",
            label=video.title,
        )
        db.session.commit()

    @staticmethod
    def remove_from_watch_later(video: YouTubeVideo) -> None:
        if video.source != "watch_later":
            raise ValueError("Only Watch Later videos can be removed.")
        video.removed_from_source = True
        video.local_history = [*video.local_history, {"event": "removed", "at": utc_iso()}]
        HistoryService.record(
            domain="youtube",
            entity_type="video",
            entity_id=video.id,
            event_type="removed_from_watch_later",
            label=video.title,
        )
        db.session.commit()
