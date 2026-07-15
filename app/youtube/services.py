from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime
from typing import Any

from app.extensions import db
from app.history.services import HistoryService
from app.shared.models import SnapshotRecord
from app.shared.text import text_direction
from app.shared.time import utc_iso, utc_now
from app.youtube.models import YouTubeVideo
from app.youtube.providers import YouTubePlaylistClient
from app.youtube.repositories import YouTubeRepository

SOURCES = {"watch_later", "pockettube"}
ORDERS = {"normal", "shuffle", "shuffle_video"}

_CHAPTER_RE = re.compile(
    r"^\s*(?P<stamp>(?:(?:\d{1,2}):)?[0-5]?\d:[0-5]\d)\s*(?:[-–—|:]\s*)?(?P<label>.*)$"
)


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


def format_duration(value: object) -> str:
    try:
        total = max(0, int(value or 0))
    except (TypeError, ValueError):
        return ""
    if total == 0:
        return ""
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _timestamp_seconds(value: str) -> int:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        return (parts[0] * 60) + parts[1]
    if len(parts) == 3:
        return (parts[0] * 3600) + (parts[1] * 60) + parts[2]
    return 0


def description_view(value: object) -> dict[str, list[dict[str, object]]]:
    """Shape cached YouTube text for a readable, safe detail view."""
    paragraphs: list[dict[str, object]] = []
    chapters: list[dict[str, object]] = []
    seen_chapters: set[int] = set()

    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        chapter = _CHAPTER_RE.match(line)
        if chapter:
            seconds = _timestamp_seconds(chapter.group("stamp"))
            label = chapter.group("label").strip() or f"Chapter at {chapter.group('stamp')}"
            if seconds not in seen_chapters:
                chapters.append(
                    {
                        "label": label,
                        "stamp": chapter.group("stamp"),
                        "seconds": seconds,
                        "direction": text_direction(label),
                    }
                )
                seen_chapters.add(seconds)
            continue
        paragraphs.append({"text": line, "direction": text_direction(line)})

    return {"paragraphs": paragraphs, "chapters": chapters}


def video_item(video: YouTubeVideo) -> dict:
    return {
        "id": video.id,
        "external_id": video.external_id,
        "title": video.title,
        "direction": text_direction(video.title),
        "channel_title": video.channel_title,
        "source": video.source,
        "group_name": video.group_name,
        "thumbnail_url": video.thumbnail_url,
        "published_at": video.published_at.isoformat() if video.published_at else None,
        "duration_seconds": video.duration_seconds,
        "duration_label": format_duration(video.duration_seconds),
        "watched": video.watched,
        "removed_from_source": video.removed_from_source,
    }


def video_detail(video: YouTubeVideo) -> dict:
    return {
        **video_item(video),
        "description": video.description,
        "description_view": description_view(video.description),
        "history": video.local_history,
    }


class YouTubeService:
    @staticmethod
    def detail_page(video: YouTubeVideo) -> dict[str, object]:
        video_ids = YouTubeRepository.ordered_ids(
            source=video.source, group=video.group_name
        )
        try:
            current_index = video_ids.index(video.id)
        except ValueError:
            current_index = -1

        if current_index >= 0:
            remaining_ids = video_ids[current_index + 1 :] + video_ids[:current_index]
            previous_id = video_ids[current_index - 1] if current_index > 0 else ""
            next_id = (
                video_ids[current_index + 1]
                if current_index + 1 < len(video_ids)
                else ""
            )
        else:
            remaining_ids = video_ids
            previous_id = ""
            next_id = ""

        related = [
            candidate
            for candidate_id in remaining_ids[:4]
            if (candidate := YouTubeRepository.get(candidate_id)) is not None
        ]
        previous = YouTubeRepository.get(previous_id) if previous_id else None
        next_video = YouTubeRepository.get(next_id) if next_id else None
        shuffle_video = (
            YouTubeRepository.get(secrets.choice(remaining_ids)) if remaining_ids else None
        )

        return {
            "video": video_detail(video),
            "related": [video_item(item) for item in related],
            "previous": video_item(previous) if previous else None,
            "next_video": video_item(next_video) if next_video else None,
            "shuffle_video": video_item(shuffle_video) if shuffle_video else None,
            "source_label": video.group_name
            or ("Watch Later" if video.source == "watch_later" else "PocketTube"),
        }

    @staticmethod
    def feed(
        *,
        source: str,
        group: str = "",
        q: str = "",
        order: str = "normal",
        limit: int = 50,
        offset: int = 0,
        seed: str = "",
    ) -> dict:
        if source not in SOURCES:
            raise ValueError("Unknown YouTube source.")
        if order not in ORDERS:
            raise ValueError("Unknown order.")
        shuffle_seed = ""
        if order in {"shuffle", "shuffle_video"}:
            videos, total = YouTubeRepository.list(
                source=source,
                group=group,
                q=q,
                limit=None,
            )
            shuffle_seed = seed.strip()[:128] or secrets.token_hex(16)
            videos.sort(
                key=lambda video: hashlib.sha256(
                    f"{shuffle_seed}\0{video.id}".encode()
                ).digest()
            )
            videos = videos[:1] if order == "shuffle_video" else videos[offset : offset + limit]
        else:
            videos, total = YouTubeRepository.list(
                source=source,
                group=group,
                q=q,
                limit=limit,
                offset=offset,
            )
        return {
            "items": [video_item(video) for video in videos],
            "total": total,
            "seed": shuffle_seed,
        }

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
        playlist_video_ids = {
            str((record.get("snippet") or {}).get("resourceId", {}).get("videoId") or "").strip()
            for record in payload
            if isinstance(record, dict)
            and isinstance((record.get("snippet") or {}).get("resourceId"), dict)
        }
        playlist_video_ids.discard("")
        missing_local_ids = set(
            db.session.scalars(
                db.select(YouTubeVideo.external_id).where(
                    YouTubeVideo.duration_seconds <= 0,
                    YouTubeVideo.removed_from_source.is_(False),
                )
            )
        )
        duration_fetcher = getattr(client, "fetch_durations", None)
        durations = (
            duration_fetcher(
                sorted(playlist_video_ids | missing_local_ids), maximum=maximum
            )
            if callable(duration_fetcher)
            else {}
        )
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
                if durations.get(external_id, 0) > 0:
                    video.duration_seconds = durations[external_id]
                video.position = position
                video.removed_from_source = False
                if not video.local_history:
                    video.local_history = [{"event": "playlist_sync", "at": utc_iso()}]

            for external_id, video in existing.items():
                if external_id not in seen and not video.removed_from_source:
                    video.removed_from_source = True
                    counts["removed"] += 1

            if durations:
                for video in db.session.scalars(
                    db.select(YouTubeVideo).where(
                        YouTubeVideo.external_id.in_(durations)
                    )
                ):
                    if durations.get(video.external_id, 0) > 0:
                        video.duration_seconds = durations[video.external_id]

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
