from __future__ import annotations

import hashlib
import random
from datetime import UTC, datetime
from typing import Any

from app.extensions import db
from app.history.services import HistoryService
from app.shared.models import SnapshotRecord
from app.shared.time import utc_iso, utc_now
from app.youtube.models import YouTubeVideo
from app.youtube.providers import YouTubePlaylistClient
from app.youtube.repositories import YouTubeRepository

SOURCES = {"watch_later", "pockettube"}
ORDERS = {"normal", "shuffle", "shuffle_video"}


def _published_at(value: object) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def _thumbnail(snippet: dict[str, Any], video_id: str) -> str:
    thumbnails = snippet.get("thumbnails") or {}
    if isinstance(thumbnails, dict):
        for size in ("maxres", "standard", "high", "medium", "default"):
            candidate = thumbnails.get(size) or {}
            url = str(candidate.get("url") or "").strip() if isinstance(candidate, dict) else ""
            if url:
                return url
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


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
    def feed(
        *,
        source: str,
        group: str = "",
        q: str = "",
        order: str = "normal",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        if source not in SOURCES:
            raise ValueError("Unknown YouTube source.")
        if order not in ORDERS:
            raise ValueError("Unknown order.")
        videos, total = YouTubeRepository.list(
            source=source,
            group=group,
            q=q,
            limit=limit,
            offset=offset,
        )
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
    def sync_watch_later(
        client: YouTubePlaylistClient,
        playlist_id: str,
        *,
        maximum: int = 5000,
    ) -> dict[str, int]:
        payload = client.fetch_playlist(playlist_id, maximum=maximum)
        existing = {
            item.external_id: item
            for item in db.session.scalars(
                db.select(YouTubeVideo).where(YouTubeVideo.source == "watch_later")
            )
        }
        seen: set[str] = set()
        counts = {"created": 0, "updated": 0, "removed": 0, "videos": 0}

        try:
            for position, record in enumerate(payload):
                snippet = record.get("snippet") or {}
                resource = snippet.get("resourceId") or {}
                external_id = str(resource.get("videoId") or "").strip()
                title = str(snippet.get("title") or "").strip()
                if not external_id or not title or external_id in seen:
                    continue
                seen.add(external_id)
                video = existing.get(external_id)
                if video is None:
                    video = YouTubeVideo(
                        external_id=external_id,
                        source="watch_later",
                        title=title[:500],
                    )
                    db.session.add(video)
                    counts["created"] += 1
                else:
                    counts["updated"] += 1
                video.playlist_item_id = str(record.get("id") or "")[:100]
                video.group_name = ""
                video.channel_id = str(
                    snippet.get("videoOwnerChannelId") or snippet.get("channelId") or ""
                )[:100]
                video.channel_title = str(
                    snippet.get("videoOwnerChannelTitle") or snippet.get("channelTitle") or ""
                )[:240]
                video.title = title[:500]
                video.description = str(snippet.get("description") or "")
                video.thumbnail_url = _thumbnail(snippet, external_id)[:1000]
                video.published_at = _published_at(snippet.get("publishedAt"))
                video.position = position
                video.removed_from_source = False
                if not video.local_history:
                    video.local_history = [{"event": "playlist_sync", "at": utc_iso()}]

            for external_id, video in existing.items():
                if external_id not in seen and not video.removed_from_source:
                    video.removed_from_source = True
                    counts["removed"] += 1

            counts["videos"] = len(seen)
            checksum = hashlib.sha256("\n".join(sorted(seen)).encode()).hexdigest()
            snapshot = db.session.scalar(
                db.select(SnapshotRecord).where(
                    SnapshotRecord.domain == "youtube_watch_later"
                )
            )
            now = utc_now()
            if snapshot is None:
                snapshot = SnapshotRecord(
                    domain="youtube_watch_later",
                    schema_version="youtube-playlist-v1",
                    relative_path="database://youtube_videos?source=watch_later",
                    checksum=checksum,
                    generated_at=now,
                    last_success_at=now,
                )
                db.session.add(snapshot)
            snapshot.checksum = checksum
            snapshot.state = "fresh"
            snapshot.message = f"{len(seen)} videos synchronized from the configured playlist."
            snapshot.generated_at = now
            snapshot.last_success_at = now
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return counts

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
