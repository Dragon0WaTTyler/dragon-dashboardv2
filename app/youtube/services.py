from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.extensions import db
from app.history.services import HistoryService
from app.shared.models import SnapshotRecord
from app.shared.text import text_direction
from app.shared.time import utc_iso, utc_now
from app.youtube.constants import POCKETTUBE_GROUP_VIDEO_LIMIT, POCKETTUBE_SHORT_MAX_SECONDS
from app.youtube.models import YouTubeVideo
from app.youtube.providers import YouTubePlaylistClient
from app.youtube.repositories import YouTubeRepository

SOURCES = {"watch_later", "pockettube"}
ORDERS = {"normal", "shuffle", "shuffle_video"}
_POCKETTUBE_ID_SEPARATOR = "::pt:"

_CHAPTER_RE = re.compile(
    r"^\s*(?P<stamp>(?:(?:\d{1,2}):)?[0-5]?\d:[0-5]\d)\s*(?:[-–—|:]\s*)?(?P<label>.*)$"
)
_HASHTAG_RE = re.compile(r"(?<!\S)?#[^\s#]+")
_SPACING_RE = re.compile(r"\s+")


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


def _canonical_external_id(value: str | None) -> str:
    return str(value or "").split(_POCKETTUBE_ID_SEPARATOR, 1)[0]


def _pockettube_external_id(video_id: str, group_name: str) -> str:
    if not group_name:
        return video_id
    group_digest = hashlib.sha1(group_name.encode("utf-8")).hexdigest()[:10]
    return f"{video_id}{_POCKETTUBE_ID_SEPARATOR}{group_digest}"


def _has_shorts_marker(snippet: dict[str, Any]) -> bool:
    haystack = f"{snippet.get('title') or ''}\n{snippet.get('description') or ''}".casefold()
    return "#shorts" in haystack or "#short" in haystack


def _is_pockettube_short(
    snippet: dict[str, Any],
    external_id: str,
    durations: dict[str, int],
) -> bool:
    duration = durations.get(external_id, 0)
    return _has_shorts_marker(snippet) or (
        0 < duration <= POCKETTUBE_SHORT_MAX_SECONDS
    )


def _cached_video_is_short(video: YouTubeVideo) -> bool:
    if 0 < video.duration_seconds <= POCKETTUBE_SHORT_MAX_SECONDS:
        return True
    return "#short" in f"{video.title}\n{video.description}".casefold()


def clean_video_title(value: object) -> str:
    original = str(value or "").strip()
    cleaned = _HASHTAG_RE.sub(" ", original)
    cleaned = _SPACING_RE.sub(" ", cleaned).strip(" \t\r\n-–—|،,؛:")
    return cleaned or original


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
    title = clean_video_title(video.title)
    return {
        "id": video.id,
        "external_id": _canonical_external_id(video.external_id),
        "title": title,
        "direction": text_direction(title),
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
    def latest_pockettube_export(downloads_dir: Path | None = None) -> Path | None:
        root = downloads_dir or (Path.home() / "Downloads")
        candidates = sorted(
            root.glob("youtube_subscription_manager_*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    @staticmethod
    def sync_pockettube(
        client: YouTubePlaylistClient,
        export_path: str | Path,
        *,
        maximum: int = 10000,
    ) -> dict[str, int]:
        path = Path(export_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError("PocketTube export could not be read.") from exc
        if not isinstance(payload, dict):
            raise ValueError("PocketTube export is not valid.")

        channel_groups: dict[str, list[str]] = {}
        group_channels: dict[str, list[str]] = {}
        for group_name, value in payload.items():
            if str(group_name).startswith("ysc_") or group_name in {"archive"}:
                continue
            if not isinstance(value, list):
                continue
            group = str(group_name).strip()[:160]
            if not group:
                continue
            for channel_id in value:
                channel = str(channel_id or "").strip()
                if channel.startswith("UC"):
                    channel_groups.setdefault(channel, []).append(group)
                    group_channels.setdefault(group, []).append(channel)

        channels = list(channel_groups)[: max(1, min(maximum, 5000))]
        channel_limits = {channel_id: 1 for channel_id in channels}
        for group, group_channel_ids in group_channels.items():
            if not group_channel_ids:
                continue
            base_need = math.ceil(POCKETTUBE_GROUP_VIDEO_LIMIT / len(group_channel_ids))
            per_channel = min(
                POCKETTUBE_GROUP_VIDEO_LIMIT,
                max(1, base_need * 2, base_need + 5),
            )
            for channel_id in group_channel_ids:
                if channel_id in channel_limits:
                    channel_limits[channel_id] = max(channel_limits[channel_id], per_channel)

        uploads_fetcher = getattr(client, "fetch_channel_uploads", None)
        if callable(uploads_fetcher):
            uploads = uploads_fetcher(channel_limits, maximum=maximum)
        else:
            latest = client.fetch_latest_channel_uploads(channels, maximum=maximum)
            uploads = {
                channel_id: [record]
                for channel_id, record in latest.items()
                if isinstance(record, dict)
            }
        durations = client.fetch_durations(
            [
                str(((record.get("snippet") or {}).get("resourceId") or {}).get("videoId") or "")
                for records in uploads.values()
                for record in records
                if isinstance(record, dict)
            ],
            maximum=maximum,
        )
        existing = {
            item.external_id: item
            for item in db.session.scalars(
                db.select(YouTubeVideo).where(YouTubeVideo.source == "pockettube")
            )
        }
        legacy_existing = {
            (item.external_id, item.group_name): item
            for item in existing.values()
            if _POCKETTUBE_ID_SEPARATOR not in item.external_id
        }
        existing_by_group: dict[str, list[YouTubeVideo]] = {}
        existing_group_keys: set[str] = set()
        for item in sorted(
            existing.values(),
            key=lambda video: (
                video.group_name,
                video.position,
                video.published_at or datetime.min.replace(tzinfo=UTC),
            ),
        ):
            group_key = _pockettube_external_id(
                _canonical_external_id(item.external_id), item.group_name
            )
            if group_key in existing_group_keys:
                continue
            existing_group_keys.add(group_key)
            existing_by_group.setdefault(item.group_name, []).append(item)
        seen: set[str] = set()
        counts = {
            "channels": len(channels),
            "created": 0,
            "updated": 0,
            "removed": 0,
            "shorts_skipped": 0,
            "videos": 0,
        }

        try:
            rows: list[tuple[datetime, str, str, list[str], dict]] = []
            candidates_seen: set[str] = set()
            for channel_id, records in uploads.items():
                for record in records:
                    snippet = record.get("snippet") or {}
                    resource = snippet.get("resourceId") or {}
                    external_id = str(resource.get("videoId") or "").strip()
                    title = str(snippet.get("title") or "").strip()
                    if not external_id or not title:
                        continue
                    if _is_pockettube_short(snippet, external_id, durations):
                        counts["shorts_skipped"] += 1
                        continue
                    groups = channel_groups.get(channel_id) or [""]
                    for group in groups:
                        primary_group = group[:160]
                        membership_id = _pockettube_external_id(external_id, primary_group)
                        if membership_id in candidates_seen:
                            continue
                        candidates_seen.add(membership_id)
                        rows.append(
                            (
                                _published_at(snippet.get("publishedAt"))
                                or datetime.min.replace(tzinfo=UTC),
                                channel_id,
                                primary_group,
                                groups,
                                record,
                            )
                        )
            rows.sort(key=lambda row: row[0], reverse=True)

            group_totals: dict[str, int] = {}
            position = 0
            for _published, channel_id, primary_group, groups, record in rows:
                snippet = record.get("snippet") or {}
                resource = snippet.get("resourceId") or {}
                external_id = str(resource.get("videoId") or "").strip()
                title = str(snippet.get("title") or "").strip()
                if (
                    primary_group
                    and group_totals.get(primary_group, 0) >= POCKETTUBE_GROUP_VIDEO_LIMIT
                ):
                    continue
                if primary_group:
                    group_totals[primary_group] = group_totals.get(primary_group, 0) + 1
                membership_id = _pockettube_external_id(external_id, primary_group)
                seen.add(membership_id)
                video = existing.get(membership_id) or legacy_existing.get(
                    (external_id, primary_group)
                )
                if video is None:
                    video = YouTubeVideo(
                        external_id=membership_id,
                        source="pockettube",
                        title=title[:500],
                    )
                    db.session.add(video)
                    counts["created"] += 1
                else:
                    video.external_id = membership_id
                    counts["updated"] += 1
                video.playlist_item_id = str(record.get("id") or "")[:100]
                video.group_name = primary_group
                video.channel_id = channel_id[:100]
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
                video.local_history = [
                    *(video.local_history or []),
                    {
                        "event": "pockettube_sync",
                        "at": utc_iso(),
                        "channel_id": channel_id,
                        "group_names": groups,
                    },
                ][-20:]
                position += 1

            for group in group_channels:
                if group_totals.get(group, 0) >= POCKETTUBE_GROUP_VIDEO_LIMIT:
                    continue
                for cached_video in existing_by_group.get(group, []):
                    if _cached_video_is_short(cached_video):
                        continue
                    membership_id = _pockettube_external_id(
                        _canonical_external_id(cached_video.external_id), group
                    )
                    if membership_id in seen:
                        continue
                    if cached_video.external_id != membership_id:
                        replacement = existing.get(membership_id)
                        if replacement is not None:
                            cached_video = replacement
                        else:
                            cached_video.external_id = membership_id
                    cached_video.removed_from_source = False
                    cached_video.position = position
                    seen.add(membership_id)
                    group_totals[group] = group_totals.get(group, 0) + 1
                    position += 1
                    if group_totals[group] >= POCKETTUBE_GROUP_VIDEO_LIMIT:
                        break

            for video in existing.values():
                if video.external_id not in seen and not video.removed_from_source:
                    video.removed_from_source = True
                    counts["removed"] += 1

            counts["videos"] = len(seen)
            checksum = hashlib.sha256("\n".join(sorted(seen)).encode()).hexdigest()
            snapshot = db.session.scalar(
                db.select(SnapshotRecord).where(
                    SnapshotRecord.domain == "youtube_pockettube"
                )
            )
            now = utc_now()
            if snapshot is None:
                snapshot = SnapshotRecord(
                    domain="youtube_pockettube",
                    schema_version="pockettube-group-cap-v2",
                    relative_path=f"file://{path.name}",
                    checksum=checksum,
                    generated_at=now,
                    last_success_at=now,
                )
                db.session.add(snapshot)
            snapshot.checksum = checksum
            snapshot.state = "fresh"
            snapshot.schema_version = "pockettube-group-cap-v2"
            snapshot.message = (
                f"{len(seen)} group-capped videos synchronized from PocketTube export."
            )
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
