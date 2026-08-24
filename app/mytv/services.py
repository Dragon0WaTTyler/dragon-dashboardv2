from __future__ import annotations

import hashlib
import re
import threading
import unicodedata
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import requests
from flask import Flask
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.extensions import db
from app.mytv.cache import query_cache
from app.mytv.models import (
    TVChannel,
    TVChannelPreference,
    TVChannelRepresentative,
    TVGroup,
    TVPlaylist,
    TVSource,
    TVTheme,
    TVThemePreference,
)

GITHUB_API = "https://api.github.com"
SOURCE_OWNER = "Dragon0WaTTyler"
SOURCE_REPOSITORY = "Dragon-IPTV-Clean"
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

# Some public playlists expose only a human-readable `tvg-name`, or carry an
# ID from a different guide provider.  These mappings use channel IDs verified
# against the XMLTV feeds configured in ``app.mytv.epg``.  Keeping the repair
# here makes it apply to every GitHub/M3U import, including regenerated source
# files, while never replacing an unrelated upstream ID.
EPG_ID_BY_CHANNEL_NAME = {
    "al jazeera": "Al.Jazeera.HD.ae",
    "al jazeera english": "Al.Jazeera.English.HD.ae",
    "al jazeera mobasher": "Al.Jazeera.Mobasher.HD.ae",
    "al jazeera mubasher": "Al.Jazeera.Mobasher.HD.ae",
    # The Belgian guide carries an independent Al Jazeera Documentary
    # schedule, rather than the duplicated placeholder present in AE1.
    "al jazeera documentary": "Al.Jazeera.Documentary.be",
    "dw arabic": "DW.Arabia.HD.ae",
    "ar docu dw arabic": "DW.Arabia.HD.ae",
    "docu dw arabic": "DW.Arabia.HD.ae",
    # These IDs are present in EPGshare's current UAE guide. Aliases cover
    # the abbreviated labels used by the imported Arabic bouquets.
    # ``geo`` is stripped by the normalizer as a geo-block marker, so the
    # abbreviated playlist label resolves to ``ad nat``.
    "ad nat": "Nat.Geo.Abu.Dhabi.HD.ae",
    "al sharq discovery": "Asharq.Discovery.HD.ae",
    "asharq documentary": "Asharq.Documentary.HD.ae",
    "al sharq documentary": "Asharq.Documentary.HD.ae",
    "authentic history": "GB3200005SO@samsungtvplus.gb",
    "autentic history": "GB3200005SO@samsungtvplus.gb",
    "discovering china": "DiscoveringChina@distro.tv",
    "rt documentary": "RTDocumentary@mts.rs",
    "rt documentary english": "RTDocumentary@mts.rs",
    "history": "History.HD.us2",
    "al arabiya news": "Al.Arabiya.HD.ae",
    "france 24": "France.24.Arabic.ae",
    "national geographic": "Nat.Geo.Abu.Dhabi.HD.ae",
    "sky news arabia": "Sky.News.Arabia.HD.ae",
    "uk vip al jazeera": "Al.Jazeera.HD.ae",
    "uk vip aljazeera news english": "Al.Jazeera.English.HD.ae",
    "uk vip france 24": "France.24.English.ae",
    # The US guide identifies this feed with its provider suffix. The EPG
    # resolver recognises that suffix as the US source family.
    "us history channel": "History.HD.us2",
    "usa history channel": "History.HD.us2",
    "usa history channel east": "History.HD.us2",
    "fbi files": "6a1610bebdf296985fd95603-6582a024a90606db3c841b1b@plex.us",
}
SUPERSEDED_EPG_IDS = {
    "aljazeeradocumentary.qa@sd",
    "al.jazeera.documentary.hd.ae",
    "asharqdocumentary.sa@sd",
    "autentichistory.de@sd",
    "discoveringchina.cn@sd",
    "fbifiles.us@uk",
    "rtdocumentary.ru@english",
}
EPG_NAME_NOISE_TOKENS = {
    "1080p",
    "720p",
    "hd",
    "fhd",
    "uhd",
    "sd",
    "geo",
    "blocked",
    "free",
    "iptv",
    "world",
    "ar",
}


class TVSyncError(RuntimeError):
    pass


def persist_theme_preference(theme: TVTheme) -> None:
    """Store only the durable ON/OFF policy, never catalogue relationships."""
    now = datetime.now(timezone.utc)
    statement = sqlite_insert(TVThemePreference).values(
        theme_key=theme.key,
        enabled=theme.enabled,
        channel_policy=theme.channel_policy,
        created_at=now,
        updated_at=now,
    )
    db.session.execute(
        statement.on_conflict_do_update(
            index_elements=[TVThemePreference.theme_key],
            set_={
                "enabled": statement.excluded.enabled,
                "channel_policy": statement.excluded.channel_policy,
                "updated_at": statement.excluded.updated_at,
            },
        )
    )


def relevant_playlist_ids(candidate_ids: list[int] | None = None) -> list[int]:
    """Return packages that currently back a favorite or an explicit ON/OFF choice."""
    conditions = [
        TVPlaylist.imported.is_(True),
        TVPlaylist.available.is_(True),
        TVPlaylist.enabled.is_(True),
        or_(
            TVTheme.enabled.is_(True),
            TVChannelPreference.favorite.is_(True),
            TVChannelPreference.enabled_override.is_not(None),
        ),
    ]
    if candidate_ids is not None:
        if not candidate_ids:
            return []
        conditions.append(TVPlaylist.id.in_(candidate_ids))
    return list(
        db.session.scalars(
            select(TVPlaylist.id)
            .join(TVChannel, TVChannel.playlist_id == TVPlaylist.id)
            .join(TVGroup, TVGroup.id == TVChannel.group_id)
            .join(TVTheme, TVTheme.id == TVGroup.theme_id)
            .outerjoin(
                TVChannelPreference,
                TVChannelPreference.preference_key == TVChannel.preference_key,
            )
            .where(*conditions)
            .distinct()
            .order_by(TVPlaylist.id)
        )
    )


def purge_unavailable_playlists(source_id: int) -> int:
    """Delete stale catalogue cache while leaving personal preference tables intact."""
    stale_ids = list(
        db.session.scalars(
            select(TVPlaylist.id).where(
                TVPlaylist.source_id == source_id,
                TVPlaylist.available.is_(False),
            )
        )
    )
    if not stale_ids:
        return 0
    stale_channel_ids = select(TVChannel.id).where(TVChannel.playlist_id.in_(stale_ids))
    db.session.execute(
        delete(TVChannelRepresentative).where(
            TVChannelRepresentative.channel_id.in_(stale_channel_ids)
        )
    )
    db.session.execute(delete(TVChannel).where(TVChannel.playlist_id.in_(stale_ids)))
    db.session.execute(delete(TVGroup).where(TVGroup.playlist_id.in_(stale_ids)))
    db.session.execute(delete(TVPlaylist).where(TVPlaylist.id.in_(stale_ids)))
    orphan_theme_ids = select(TVTheme.id).outerjoin(TVGroup).group_by(TVTheme.id).having(
        func.count(TVGroup.id) == 0
    )
    db.session.execute(delete(TVTheme).where(TVTheme.id.in_(orphan_theme_ids)))
    db.session.commit()
    query_cache.invalidate()
    return len(stale_ids)


def prune_irrelevant_playlist_cache(source_id: int) -> int:
    """Keep channel cache only for packages backing current personal choices."""
    relevant = set(relevant_playlist_ids())
    candidates = list(
        db.session.scalars(
            select(TVPlaylist.id).where(
                TVPlaylist.source_id == source_id,
                TVPlaylist.available.is_(True),
                TVPlaylist.imported.is_(True),
            )
        )
    )
    disposable_ids = [playlist_id for playlist_id in candidates if playlist_id not in relevant]
    if not disposable_ids:
        return 0
    disposable_channel_ids = select(TVChannel.id).where(
        TVChannel.playlist_id.in_(disposable_ids)
    )
    db.session.execute(
        delete(TVChannelRepresentative).where(
            TVChannelRepresentative.channel_id.in_(disposable_channel_ids)
        )
    )
    db.session.execute(delete(TVChannel).where(TVChannel.playlist_id.in_(disposable_ids)))
    db.session.execute(delete(TVGroup).where(TVGroup.playlist_id.in_(disposable_ids)))
    db.session.execute(
        update(TVPlaylist)
        .where(TVPlaylist.id.in_(disposable_ids))
        .values(
            imported=False,
            imported_sha="",
            channel_count=0,
            group_count=0,
            sync_status="catalogued",
            sync_error="",
            last_synced_at=None,
        )
    )
    orphan_theme_ids = select(TVTheme.id).outerjoin(TVGroup).group_by(TVTheme.id).having(
        func.count(TVGroup.id) == 0
    )
    db.session.execute(delete(TVTheme).where(TVTheme.id.in_(orphan_theme_ids)))
    db.session.commit()
    query_cache.invalidate()
    return len(disposable_ids)


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


def _epg_channel_name_key(value: str) -> str:
    """Normalize a playlist label without format, provider, or quality noise."""

    normalized = unicodedata.normalize("NFKD", str(value or "")).casefold()
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    tokens = re.findall(r"[a-z0-9]+", normalized)
    return " ".join(token for token in tokens if token not in EPG_NAME_NOISE_TOKENS)


def resolved_epg_id(name: str, current_id: str = "") -> str:
    """Return a verified XMLTV ID for a known channel when an import needs repair."""

    mapped_id = EPG_ID_BY_CHANNEL_NAME.get(_epg_channel_name_key(name))
    if mapped_id and (
        not current_id.strip() or current_id.strip().casefold() in SUPERSEDED_EPG_IDS
    ):
        return mapped_id
    return current_id.strip()


def with_resolved_epg_id(entry: ChannelEntry) -> ChannelEntry:
    resolved_id = resolved_epg_id(entry.tvg_name or entry.name, entry.tvg_id)
    if resolved_id == entry.tvg_id:
        return entry
    return ChannelEntry(
        name=entry.name,
        group=entry.group,
        url=entry.url,
        tvg_id=resolved_id,
        tvg_name=entry.tvg_name,
        logo_url=entry.logo_url,
        kind=entry.kind,
    )


def migrate_epg_preferences() -> int:
    """Move EPG repairs across preferences and their current catalogue rows."""

    preferences = list(db.session.scalars(select(TVChannelPreference)))
    by_key = {item.preference_key: item for item in preferences}
    migrated = 0
    for preference in preferences:
        resolved_id = resolved_epg_id(preference.name, preference.tvg_id)
        if not resolved_id or resolved_id == preference.tvg_id:
            continue
        destination_key = ChannelEntry(
            preference.name, preference.theme_key, "", tvg_id=resolved_id
        ).preference_key(preference.theme_key)
        old_key = preference.preference_key
        channels = list(
            db.session.scalars(
                select(TVChannel).where(TVChannel.preference_key == old_key)
            )
        )
        destination = by_key.get(destination_key)
        if destination is not None and destination is not preference:
            destination.favorite = destination.favorite or preference.favorite
            destination.enabled_override = (
                destination.enabled_override
                if destination.enabled_override is not None
                else preference.enabled_override
            )
            destination.watch_count += preference.watch_count
            if (
                preference.last_watched_at is not None
                and (
                    destination.last_watched_at is None
                    or preference.last_watched_at > destination.last_watched_at
                )
            ):
                destination.last_watched_at = preference.last_watched_at
            db.session.delete(preference)
        else:
            by_key.pop(preference.preference_key, None)
            preference.preference_key = destination_key
            preference.tvg_id = resolved_id
            by_key[destination_key] = preference
        for channel in channels:
            channel.preference_key = destination_key
            channel.tvg_id = resolved_id
            # Keep imports idempotent after the repair. The same playlist
            # entry should match this row instead of creating a detached copy.
            channel.external_key = ChannelEntry(
                channel.name, "", "", tvg_id=resolved_id, tvg_name=channel.tvg_name
            ).external_key
        migrated += 1
    return migrated


@dataclass(frozen=True, slots=True)
class ThemeIdentity:
    key: str
    name: str


def smart_theme(group_name: str) -> ThemeIdentity:
    """Collapse equivalent source bouquets into one stable cross-package theme."""
    display = re.sub(r"\s+", " ", str(group_name or "Ungrouped")).strip()
    display = re.sub(r"\s*[|:»›]+\s*", " · ", display).strip(" ·-") or "Ungrouped"
    folded = (
        unicodedata.normalize("NFKD", display.casefold()).encode("ascii", "ignore").decode("ascii")
    )
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
            attributes = {key.lower(): value.strip() for key, value in ATTRIBUTE_RE.findall(line)}
            name = line.rsplit(",", 1)[-1].strip() if "," in line else "Unknown channel"
            pending = {
                "name": name or attributes.get("tvg-name", "Unknown channel"),
                "group": attributes.get("group-title", "Ungrouped") or "Ungrouped",
                "tvg_id": attributes.get("tvg-id", ""),
                "tvg_name": attributes.get("tvg-name", ""),
                "logo_url": attributes.get("tvg-logo", ""),
                "kind": (
                    attributes.get("dragon-stream-kind", "")
                    if attributes.get("dragon-stream-kind", "")
                    in {"hls", "file", "transport", "stream"}
                    else ""
                ),
            }
            continue
        if line.startswith("#"):
            continue
        if pending and line.lower().startswith(("http://", "https://")):
            kind = pending.pop("kind") or classify_stream(line)
            yield ChannelEntry(**pending, url=line, kind=kind)
            pending = None


def friendly_playlist_name(filename: str) -> str:
    parts = filename.rsplit("_Hunter_", 1)
    if len(parts) == 2:
        stamp = parts[0].replace("FIW_", "").split("_", 1)[0]
        code = parts[1].removesuffix(".m3u")
        try:
            moment = datetime.fromtimestamp(int(stamp), tz=timezone.utc).strftime("%d %b · %H:%M")
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
        self.source_id: int | None = None
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "User-Agent": "Dragon-My-TV/1.0",
            }
        )

    def discover(self, source: TVSource | None = None) -> list[int]:
        if source is None:
            source = db.session.scalar(select(TVSource).where(TVSource.protected.is_(True)))
        if source is None:
            source = TVSource(
                name="Dragon IPTV catalogue",
                source_type="github_repository",
                locator=f"{SOURCE_OWNER}/{SOURCE_REPOSITORY}",
                branch=SOURCE_BRANCH,
                file_pattern="*.m3u",
                enabled=True,
                auto_refresh=True,
                refresh_interval_minutes=360,
                protected=True,
                status="untested",
            )
            db.session.add(source)
            db.session.flush()
        self.source_id = source.id
        repository = source.locator.strip()
        branch = source.branch.strip() or SOURCE_BRANCH
        response = self.session.get(
            f"{GITHUB_API}/repos/{repository}/git/trees/{quote(branch, safe='/')}",
            params={"recursive": "1"},
            timeout=self.timeout_seconds,
        )
        if response.status_code != 200:
            raise TVSyncError(f"GitHub returned HTTP {response.status_code}.")
        payload = response.json()
        if isinstance(payload, list):
            # Keep compatibility with GitHub's root-contents response and the
            # compact test fixture used by earlier Dragon installations.
            files = [
                item
                for item in payload
                if item.get("type") == "file"
                and str(item.get("name") or "").lower().endswith((".m3u", ".m3u8"))
            ]
        elif isinstance(payload, dict):
            tree = payload.get("tree")
            if not isinstance(tree, list):
                raise TVSyncError("GitHub returned an invalid catalogue.")
            files = []
            for item in tree:
                path = str(item.get("path") or "")
                if item.get("type") != "blob" or not path.lower().endswith((".m3u", ".m3u8")):
                    continue
                files.append(
                    {
                        "type": "file",
                        "name": Path(path).name,
                        "path": path,
                        "download_url": (
                            "https://raw.githubusercontent.com/"
                            f"{repository}/{quote(branch, safe='/')}/{quote(path, safe='/')}"
                        ),
                        "sha": str(item.get("sha") or ""),
                        "size": int(item.get("size") or 0),
                    }
                )
        else:
            raise TVSyncError("GitHub returned an invalid catalogue.")
        files.sort(key=lambda item: str(item.get("path") or item.get("name") or ""))

        db.session.execute(
            update(TVPlaylist).where(TVPlaylist.source_id == source.id).values(available=False)
        )
        self.new_ids = []
        self.changed_ids = []
        self.pending_ids = []
        ids: list[int] = []
        for item in files:
            path = str(item["path"])
            playlist = db.session.scalar(select(TVPlaylist).where(TVPlaylist.github_path == path))
            if playlist is None:
                playlist = TVPlaylist(
                    source_id=source.id,
                    name=friendly_playlist_name(str(item["name"])),
                    github_path=path,
                    source_url=str(item["download_url"]),
                    enabled=True,
                )
                db.session.add(playlist)
                is_new = True
            else:
                is_new = False
            playlist.source_id = source.id
            playlist.name = friendly_playlist_name(str(item["name"]))
            playlist.source_url = str(item["download_url"])
            playlist.source_sha = str(item.get("sha") or "")
            playlist.size_bytes = int(item.get("size") or 0)
            playlist.available = True
            playlist.discovered_at = datetime.now(timezone.utc)
            db.session.flush()
            ids.append(playlist.id)
            if is_new:
                self.new_ids.append(playlist.id)
            elif playlist.imported and playlist.imported_sha != playlist.source_sha:
                self.changed_ids.append(playlist.id)
            if not playlist.imported:
                self.pending_ids.append(playlist.id)
        source.status = "healthy"
        source.last_error = ""
        source.last_tested_at = datetime.now(timezone.utc)
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
        theme_preferences = {
            item.theme_key: item
            for item in db.session.scalars(select(TVThemePreference))
        }
        custom_source = bool(playlist.source and not playlist.source.protected)
        auto_enabled_themes: dict[str, TVTheme] = {}
        for theme_key, theme in themes.items():
            durable = theme_preferences.get(theme_key)
            if durable is not None:
                theme.enabled = durable.enabled
                theme.channel_policy = durable.channel_policy
        migrate_epg_preferences()
        preferences = {
            item.preference_key: item for item in db.session.scalars(select(TVChannelPreference))
        }
        affected_theme_ids = {item.theme_id for item in groups.values()}
        parsed_count = 0
        batch: list[dict[str, Any]] = []
        try:
            with ExitStack() as stack:
                local_path = Path(playlist.source_url)
                if playlist.source and playlist.source.source_type == "local_file":
                    if not local_path.is_file():
                        raise TVSyncError("The uploaded playlist file is missing.")
                    lines = stack.enter_context(
                        local_path.open("r", encoding="utf-8-sig", errors="replace")
                    )
                else:
                    response = stack.enter_context(
                        self.session.get(
                            playlist.source_url,
                            stream=True,
                            timeout=(self.timeout_seconds, max(60, self.timeout_seconds * 6)),
                        )
                    )
                    if response.status_code != 200:
                        raise TVSyncError(
                            f"Playlist download returned HTTP {response.status_code}."
                        )
                    response.encoding = response.encoding or "utf-8"
                    lines = response.iter_lines(decode_unicode=True)
                for position, raw_entry in enumerate(parse_m3u(lines), start=1):
                    entry = with_resolved_epg_id(raw_entry)
                    identity = smart_theme(entry.group)
                    theme = themes.get(identity.key)
                    if theme is None:
                        durable = theme_preferences.get(identity.key)
                        theme = TVTheme(
                            key=identity.key,
                            name=identity.name,
                            enabled=durable.enabled if durable else custom_source,
                            channel_policy=durable.channel_policy if durable else None,
                        )
                        db.session.add(theme)
                        db.session.flush()
                        themes[identity.key] = theme
                        if custom_source and durable is None:
                            auto_enabled_themes[identity.key] = theme
                    elif custom_source and identity.key not in theme_preferences:
                        theme.enabled = True
                        auto_enabled_themes[identity.key] = theme
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
                    select(func.count(TVChannel.id)).where(TVChannel.playlist_id == playlist_id)
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
            playlist.imported_sha = playlist.source_sha
            playlist.channel_count = stored_count
            playlist.group_count = stored_groups
            playlist.sync_status = "ready"
            playlist.sync_error = ""
            playlist.last_synced_at = datetime.now(timezone.utc)
            if playlist.source:
                playlist.source.status = "healthy"
                playlist.source.last_error = ""
                playlist.source.last_success_at = datetime.now(timezone.utc)
            for auto_enabled_theme in auto_enabled_themes.values():
                persist_theme_preference(auto_enabled_theme)
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
                WHERE playlists.imported = 1 AND playlists.available = 1 AND playlists.enabled = 1
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
                    changed = list(dict.fromkeys([*sync.changed_ids, *sync.pending_ids]))
                    selected = relevant_playlist_ids(changed)
                    if not selected and not db.session.scalar(select(func.count(TVTheme.id))):
                        selected = changed[-1:]
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
                        self._status["message"] = f"Importing package {index} of {len(selected)}"

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
                purged = purge_unavailable_playlists(sync.source_id) if sync.source_id else 0
                pruned = (
                    prune_irrelevant_playlist_cache(sync.source_id)
                    if sync.source_id and mode in {"catalog", "fetch"}
                    else 0
                )
                sync.refresh_representatives()
                if sync.source_id:
                    source = db.session.get(TVSource, sync.source_id)
                    if source:
                        source.last_success_at = datetime.now(timezone.utc)
                        db.session.commit()
                with self._lock:
                    self._status.update(
                        state="complete",
                        message=(
                            f"Catalogue refreshed · {purged + pruned} unused package(s) cleaned"
                            if not selected
                            else f"Updated {len(selected)} selected package(s)"
                        ),
                    )
        except Exception as error:
            with self._lock:
                self._status.update(state="error", message="Sync failed", error=str(error)[:500])


sync_coordinator = TVSyncCoordinator()
