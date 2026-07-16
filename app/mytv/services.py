from __future__ import annotations

import hashlib
import re
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import requests
from flask import Flask
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.extensions import db
from app.mytv.cache import query_cache
from app.mytv.models import (
    TVChannel,
    TVChannelPreference,
    TVChannelRepresentative,
    TVGroup,
    TVPlaylist,
    TVTheme,
)

GITHUB_API = "https://api.github.com"
SOURCE_OWNER = "mesbahikarim63-commits"
SOURCE_REPOSITORY = "hot-dodo"
SOURCE_BRANCH = "main"
ATTRIBUTE_RE = re.compile(r'([\w-]+)="([^"]*)"')
THEME_UMBRELLA_PREFIXES = {"afr", "arab", "asia", "euro", "lame", "name"}
THEME_TOKEN_ALIASES = {
    "de": "germany",
    "deutschland": "germany",
    "espana": "spain",
    "fr": "france",
    "franch": "france",
    "it": "italy",
    "italia": "italy",
    "nl": "netherlands",
    "pt": "portugal",
}
THEME_PHRASE_ALIASES = {
    "united arab emirates": "uae",
    "united kingdom": "uk",
    "united states": "usa",
}


class TVSyncError(RuntimeError):
    pass


@dataclass(slots=True)
class ChannelEntry:
    name: str
    group: str
    url: str
    tvg_id: str = ""
    tvg_name: str = ""
    logo_url: str = ""
    kind: str = "stream"

    @property
    def external_key(self) -> str:
        identity = "\x1f".join(
            (
                self.tvg_id.strip().casefold(),
                self.tvg_name.strip().casefold(),
                self.name.strip().casefold(),
                self.group.strip().casefold(),
            )
        )
        return hashlib.sha256(identity.encode("utf-8", "ignore")).hexdigest()

    def preference_key(self, theme_key: str) -> str:
        stable_id = self.tvg_id.strip().casefold()
        if stable_id:
            identity = f"tvg-id\x1f{stable_id}"
        else:
            stable_name = self.tvg_name.strip() or self.name.strip()
            normalized_name = re.sub(r"\s+", " ", stable_name).casefold()
            identity = f"theme\x1f{theme_key}\x1fname\x1f{normalized_name}"
        return hashlib.sha256(identity.encode("utf-8", "ignore")).hexdigest()


@dataclass(frozen=True, slots=True)
class ThemeIdentity:
    key: str
    name: str


def smart_theme(group_name: str) -> ThemeIdentity:
    """Collapse equivalent source bouquets into one stable cross-package theme."""
    display = re.sub(r"\s+", " ", str(group_name or "Ungrouped")).strip()
    display = re.sub(r"\s*[|:»›]+\s*", " · ", display).strip(" ·-") or "Ungrouped"
    folded = unicodedata.normalize("NFKD", display.casefold()).encode(
        "ascii", "ignore"
    ).decode("ascii")
    for phrase, replacement in THEME_PHRASE_ALIASES.items():
        folded = folded.replace(phrase, replacement)
    tokens = re.findall(r"[a-z0-9]+", folded)
    if len(tokens) > 1 and tokens[0] in THEME_UMBRELLA_PREFIXES:
        tokens.pop(0)
    normalized = [THEME_TOKEN_ALIASES.get(token, token) for token in tokens]
    deduplicated: list[str] = []
    for token in normalized:
        if not deduplicated or deduplicated[-1] != token:
            deduplicated.append(token)
    key = "-".join(deduplicated) or "ungrouped"
    if len(key) > 220:
        digest = hashlib.sha256(key.encode()).hexdigest()[:16]
        key = f"{key[:200]}-{digest}"
    return ThemeIdentity(key=key, name=display)


def classify_stream(url: str) -> str:
    path = urlsplit(url).path.lower()
    if path.endswith((".m3u8", ".m3u")):
        return "hls"
    if path.endswith((".mp4", ".webm", ".mov")):
        return "file"
    if path.endswith((".ts", ".mpegts")):
        return "transport"
    return "stream"


def parse_m3u(lines):
    pending: dict[str, str] | None = None
    for raw_line in lines:
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8-sig", "replace")
        else:
            line = str(raw_line).lstrip("\ufeff")
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            attributes = {
                key.lower(): value.strip() for key, value in ATTRIBUTE_RE.findall(line)
            }
            name = line.rsplit(",", 1)[-1].strip() if "," in line else "Unknown channel"
            pending = {
                "name": name or attributes.get("tvg-name", "Unknown channel"),
                "group": attributes.get("group-title", "Ungrouped") or "Ungrouped",
                "tvg_id": attributes.get("tvg-id", ""),
                "tvg_name": attributes.get("tvg-name", ""),
                "logo_url": attributes.get("tvg-logo", ""),
            }
            continue
        if line.startswith("#"):
            continue
        if pending and line.lower().startswith(("http://", "https://")):
            yield ChannelEntry(**pending, url=line, kind=classify_stream(line))
            pending = None


def friendly_playlist_name(filename: str) -> str:
    parts = filename.rsplit("_Hunter_", 1)
    if len(parts) == 2:
        stamp = parts[0].replace("FIW_", "").split("_", 1)[0]
        code = parts[1].removesuffix(".m3u")
        try:
            moment = datetime.fromtimestamp(int(stamp), tz=UTC).strftime("%d %b · %H:%M")
            return f"Package {code} · {moment}"
        except (OSError, ValueError):
            pass
    return filename.removesuffix(".m3u").replace("_", " ")


class GithubTVSync:
    def __init__(self, session: requests.Session | None = None, timeout_seconds: int = 20):
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self.new_ids: list[int] = []
        self.changed_ids: list[int] = []
        self.pending_ids: list[int] = []
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "User-Agent": "Dragon-My-TV/1.0",
            }
        )

    def discover(self) -> list[int]:
        response = self.session.get(
            f"{GITHUB_API}/repos/{SOURCE_OWNER}/{SOURCE_REPOSITORY}/contents",
            params={"ref": SOURCE_BRANCH},
            timeout=self.timeout_seconds,
        )
        if response.status_code != 200:
            raise TVSyncError(f"GitHub returned HTTP {response.status_code}.")
        payload = response.json()
        if not isinstance(payload, list):
            raise TVSyncError("GitHub returned an invalid catalogue.")
        files = sorted(
            (
                item
                for item in payload
                if item.get("type") == "file"
                and str(item.get("name") or "").lower().endswith(".m3u")
            ),
            key=lambda item: str(item.get("name") or ""),
        )

        db.session.execute(update(TVPlaylist).values(available=False))
        self.new_ids = []
        self.changed_ids = []
        self.pending_ids = []
        ids: list[int] = []
        for item in files:
            path = str(item["path"])
            playlist = db.session.scalar(
                select(TVPlaylist).where(TVPlaylist.github_path == path)
            )
            if playlist is None:
                playlist = TVPlaylist(
                    name=friendly_playlist_name(str(item["name"])),
                    github_path=path,
                    source_url=str(item["download_url"]),
                    enabled=True,
                )
                db.session.add(playlist)
                is_new = True
            else:
                is_new = False
            playlist.name = friendly_playlist_name(str(item["name"]))
            playlist.source_url = str(item["download_url"])
            playlist.source_sha = str(item.get("sha") or "")
            playlist.size_bytes = int(item.get("size") or 0)
            playlist.enabled = True
            playlist.available = True
            playlist.discovered_at = datetime.now(UTC)
            db.session.flush()
            ids.append(playlist.id)
            if is_new:
                self.new_ids.append(playlist.id)
            elif playlist.imported and playlist.imported_sha != playlist.source_sha:
                self.changed_ids.append(playlist.id)
            if not playlist.imported:
                self.pending_ids.append(playlist.id)
        db.session.commit()
        query_cache.invalidate()
        return ids

    def import_playlist(
        self, playlist_id: int, progress=None, *, refresh_representatives: bool = True
    ) -> dict[str, int]:
        playlist = db.session.get(TVPlaylist, playlist_id)
        if playlist is None:
            raise TVSyncError("Playlist was not found.")
        playlist.sync_status = "syncing"
        playlist.sync_error = ""
        db.session.commit()

        token = uuid.uuid4().hex
        groups = {
            item.name: item
            for item in db.session.scalars(
                select(TVGroup).where(TVGroup.playlist_id == playlist_id)
            )
        }
        themes = {item.key: item for item in db.session.scalars(select(TVTheme))}
        preferences = {
            item.preference_key: item
            for item in db.session.scalars(select(TVChannelPreference))
        }
        affected_theme_ids = {item.theme_id for item in groups.values()}
        parsed_count = 0
        batch: list[dict[str, Any]] = []
        try:
            with self.session.get(
                playlist.source_url,
                stream=True,
                timeout=(self.timeout_seconds, max(60, self.timeout_seconds * 6)),
            ) as response:
                if response.status_code != 200:
                    raise TVSyncError(
                        f"Playlist download returned HTTP {response.status_code}."
                    )
                response.encoding = response.encoding or "utf-8"
                for position, entry in enumerate(
                    parse_m3u(response.iter_lines(decode_unicode=True)), start=1
                ):
                    identity = smart_theme(entry.group)
                    theme = themes.get(identity.key)
                    if theme is None:
                        theme = TVTheme(
                            key=identity.key,
                            name=identity.name,
                            enabled=False,
                        )
                        db.session.add(theme)
                        db.session.flush()
                        themes[identity.key] = theme
                    group = groups.get(entry.group)
                    if group is None:
                        group = TVGroup(
                            playlist_id=playlist_id,
                            theme_id=theme.id,
                            name=entry.group,
                            enabled=False,
                        )
                        db.session.add(group)
                        db.session.flush()
                        groups[entry.group] = group
                    elif group.theme_id != theme.id:
                        group.theme_id = theme.id
                    affected_theme_ids.add(theme.id)
                    preference_key = entry.preference_key(theme.key)
                    preference = preferences.get(preference_key)
                    batch.append(
                        {
                            "playlist_id": playlist_id,
                            "group_id": group.id,
                            "external_key": entry.external_key,
                            "preference_key": preference_key,
                            "name": entry.name,
                            "tvg_id": entry.tvg_id,
                            "tvg_name": entry.tvg_name,
                            "logo_url": entry.logo_url,
                            "stream_url": entry.url,
                            "stream_kind": entry.kind,
                            "enabled_override": (
                                preference.enabled_override if preference else None
                            ),
                            "position": position,
                            "last_seen_sync": token,
                        }
                    )
                    parsed_count += 1
                    if len(batch) >= 500:
                        self._upsert_channels(batch)
                        batch.clear()
                        if progress:
                            progress(parsed_count)
            if batch:
                self._upsert_channels(batch)
            db.session.execute(
                delete(TVChannel).where(
                    TVChannel.playlist_id == playlist_id,
                    TVChannel.last_seen_sync != token,
                )
            )
            for group in groups.values():
                group.channel_count = int(
                    db.session.scalar(
                        select(func.count(TVChannel.id)).where(TVChannel.group_id == group.id)
                    )
                    or 0
                )
                if group.channel_count == 0:
                    db.session.delete(group)
            db.session.flush()
            aggregates = {
                theme_id: (int(group_count), int(channel_count or 0))
                for theme_id, group_count, channel_count in db.session.execute(
                    select(
                        TVGroup.theme_id,
                        func.count(TVGroup.id),
                        func.sum(TVGroup.channel_count),
                    )
                    .where(TVGroup.theme_id.in_(affected_theme_ids))
                    .group_by(TVGroup.theme_id)
                )
            }
            for theme_id in affected_theme_ids:
                theme = db.session.get(TVTheme, theme_id)
                if theme is None:
                    continue
                counts = aggregates.get(theme_id)
                if counts is None:
                    theme.group_count = 0
                    theme.channel_count = 0
                else:
                    theme.group_count, theme.channel_count = counts
            stored_count = int(
                db.session.scalar(
                    select(func.count(TVChannel.id)).where(
                        TVChannel.playlist_id == playlist_id
                    )
                )
                or 0
            )
            stored_groups = int(
                db.session.scalar(
                    select(func.count(TVGroup.id)).where(TVGroup.playlist_id == playlist_id)
                )
                or 0
            )
            playlist.imported = True
            playlist.enabled = True
            playlist.imported_sha = playlist.source_sha
            playlist.channel_count = stored_count
            playlist.group_count = stored_groups
            playlist.sync_status = "ready"
            playlist.sync_error = ""
            playlist.last_synced_at = datetime.now(UTC)
            db.session.commit()
            if refresh_representatives:
                self.refresh_representatives()
            query_cache.invalidate()
            return {
                "playlist_id": playlist_id,
                "channels": stored_count,
                "groups": stored_groups,
                "parsed_channels": parsed_count,
            }
        except Exception as error:
            db.session.rollback()
            failed = db.session.get(TVPlaylist, playlist_id)
            if failed is not None:
                failed.sync_status = "error"
                failed.sync_error = str(error)[:500]
                db.session.commit()
                query_cache.invalidate()
            raise

    @staticmethod
    def refresh_representatives() -> None:
        """Materialize one row per logical channel for fast catalogue reads."""
        db.session.execute(delete(TVChannelRepresentative))
        db.session.execute(
            text(
                """
                INSERT INTO tv_channel_representatives (preference_key, channel_id)
                SELECT channels.preference_key, MAX(channels.id)
                FROM tv_channels AS channels
                JOIN tv_playlists AS playlists ON playlists.id = channels.playlist_id
                WHERE playlists.imported = 1 AND playlists.available = 1
                GROUP BY channels.preference_key
                """
            )
        )
        db.session.commit()
        query_cache.invalidate()

    @staticmethod
    def _upsert_channels(rows: list[dict[str, Any]]) -> None:
        statement = sqlite_insert(TVChannel).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=[TVChannel.playlist_id, TVChannel.external_key],
            set_={
                "group_id": statement.excluded.group_id,
                "preference_key": statement.excluded.preference_key,
                "name": statement.excluded.name,
                "tvg_id": statement.excluded.tvg_id,
                "tvg_name": statement.excluded.tvg_name,
                "logo_url": statement.excluded.logo_url,
                "stream_url": statement.excluded.stream_url,
                "stream_kind": statement.excluded.stream_kind,
                "enabled_override": statement.excluded.enabled_override,
                "position": statement.excluded.position,
                "last_seen_sync": statement.excluded.last_seen_sync,
            },
        )
        db.session.execute(statement)


class TVSyncCoordinator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status: dict[str, Any] = {
            "state": "idle",
            "mode": None,
            "message": "Ready",
            "current": 0,
            "total": 0,
            "channels": 0,
            "error": None,
            "new_files": 0,
            "changed_files": 0,
            "pending_files": 0,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def start(self, app: Flask, mode: str, playlist_ids: list[int]) -> bool:
        with self._lock:
            if self._status["state"] == "running":
                return False
            self._status.update(
                state="running",
                mode=mode,
                message="Connecting to source…",
                current=0,
                total=0,
                channels=0,
                error=None,
                new_files=0,
                changed_files=0,
                pending_files=0,
            )
        threading.Thread(
            target=self._run,
            args=(app, mode, playlist_ids),
            daemon=True,
            name="dragon-mytv-sync",
        ).start()
        return True

    def _run(self, app: Flask, mode: str, playlist_ids: list[int]) -> None:
        try:
            with app.app_context():
                sync = GithubTVSync()
                discovered = sync.discover()
                with self._lock:
                    self._status["new_files"] = len(sync.new_ids)
                    self._status["changed_files"] = len(sync.changed_ids)
                    self._status["pending_files"] = len(sync.pending_ids)
                if mode == "catalog":
                    selected: list[int] = []
                elif mode == "fetch":
                    selected = list(
                        dict.fromkeys([*sync.changed_ids, *sync.pending_ids])
                    )
                elif mode == "all":
                    selected = discovered
                elif mode == "selected":
                    selected = [item for item in playlist_ids if item in discovered]
                else:
                    selected = discovered[-3:]
                with self._lock:
                    self._status["total"] = len(selected)
                    self._status["message"] = (
                        f"Found {len(discovered)} packages"
                        if not selected
                        else f"Importing {len(selected)} packages…"
                    )
                total_channels = 0
                for index, playlist_id in enumerate(selected, start=1):
                    with self._lock:
                        self._status["current"] = index
                        self._status["message"] = (
                            f"Importing package {index} of {len(selected)}"
                        )

                    def update_progress(count: int, base: int = total_channels) -> None:
                        with self._lock:
                            self._status["channels"] = base + count

                    result = sync.import_playlist(
                        playlist_id,
                        update_progress,
                        refresh_representatives=False,
                    )
                    total_channels += result["channels"]
                    with self._lock:
                        self._status["channels"] = total_channels
                sync.refresh_representatives()
                with self._lock:
                    self._status.update(
                        state="complete",
                        message=(
                            "Source catalogue refreshed"
                            if not selected
                            else f"Imported {total_channels:,} channels"
                        ),
                    )
        except Exception as error:
            with self._lock:
                self._status.update(
                    state="error", message="Sync failed", error=str(error)[:500]
                )


sync_coordinator = TVSyncCoordinator()
