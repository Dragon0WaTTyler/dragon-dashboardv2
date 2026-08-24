from __future__ import annotations

import fnmatch
import hashlib
import re
from datetime import timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from flask import current_app
from sqlalchemy import func, select, update
from werkzeug.datastructures import FileStorage, MultiDict
from werkzeug.utils import secure_filename

from app.extensions import db
from app.services.streaming import UnsafeStreamUrl, validate_stream_url
from app.shared.time import utc_now

from .cache import query_cache
from .models import TVGroup, TVPlaylist, TVSource, TVTheme, TVThemePreference
from .services import (
    GithubTVSync,
    friendly_playlist_name,
    persist_theme_preference,
    prune_irrelevant_playlist_cache,
    purge_unavailable_playlists,
    relevant_playlist_ids,
)

SOURCE_TYPES = {
    "m3u_url": "M3U URL",
    "github_repository": "GitHub repository",
    "github_file": "GitHub file",
    "local_file": "Local M3U file",
}
REFRESH_INTERVALS = {15, 30, 60, 180, 360, 720, 1440}
GITHUB_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class TVSourceValidationError(ValueError):
    pass


def _public_response(session: requests.Session, url: str, *, timeout: int = 20):
    current_url = url
    for _ in range(4):
        validate_stream_url(current_url)
        response = session.get(
            current_url,
            stream=True,
            allow_redirects=False,
            timeout=(timeout, max(30, timeout * 3)),
            headers={"User-Agent": "Dragon-Source-Manager/1.0"},
        )
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("Location")
        response.close()
        if not location:
            raise TVSourceValidationError("The source redirected without a destination.")
        current_url = urljoin(current_url, location)
    raise TVSourceValidationError("The source redirected too many times.")


def _repository_slug(value: str) -> str:
    candidate = value.strip().removesuffix(".git")
    if candidate.startswith(("http://", "https://")):
        parsed = urlsplit(candidate)
        if parsed.hostname not in {"github.com", "www.github.com"}:
            raise TVSourceValidationError("Use a public github.com repository URL.")
        candidate = parsed.path.strip("/").removesuffix(".git")
    parts = candidate.split("/")
    if len(parts) != 2 or not GITHUB_REPOSITORY_RE.fullmatch(candidate):
        raise TVSourceValidationError("Repository must use owner/repository format.")
    return candidate


def _github_raw_url(value: str) -> str:
    candidate = value.strip()
    parsed = urlsplit(candidate)
    if parsed.hostname == "raw.githubusercontent.com":
        return candidate
    if parsed.hostname not in {"github.com", "www.github.com"}:
        raise TVSourceValidationError("Use a GitHub file or raw.githubusercontent.com URL.")
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 5 or parts[2] not in {"blob", "raw"}:
        raise TVSourceValidationError("GitHub file URL must include /blob/branch/file.m3u.")
    owner, repository, _, branch, *path = parts
    return f"https://raw.githubusercontent.com/{owner}/{repository}/{branch}/{'/'.join(path)}"


def _validate_m3u_name(filename: str) -> None:
    if not filename.casefold().endswith((".m3u", ".m3u8")):
        raise TVSourceValidationError("Choose an .m3u or .m3u8 playlist file.")


class TVSourceManager:
    def __init__(self, session: requests.Session | None = None, timeout_seconds: int = 20):
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def list_sources() -> list[dict]:
        sources = list(
            db.session.scalars(select(TVSource).order_by(TVSource.created_at, TVSource.id))
        )
        rows = {
            int(source_id): (int(playlists), int(channels or 0))
            for source_id, playlists, channels in db.session.execute(
                select(
                    TVPlaylist.source_id,
                    func.count(func.distinct(TVPlaylist.id)),
                    func.sum(TVPlaylist.channel_count),
                )
                .where(TVPlaylist.source_id.is_not(None))
                .group_by(TVPlaylist.source_id)
            )
        }
        return [
            {
                "record": source,
                "type_label": SOURCE_TYPES.get(source.source_type, source.source_type),
                "playlist_count": rows.get(source.id, (0, 0))[0],
                "channel_count": rows.get(source.id, (0, 0))[1],
            }
            for source in sources
        ]

    @staticmethod
    def due_sources() -> list[TVSource]:
        now = utc_now()
        due = []
        for source in db.session.scalars(
            select(TVSource).where(TVSource.enabled.is_(True), TVSource.auto_refresh.is_(True))
        ):
            last_success = source.last_success_at
            if last_success is not None and last_success.tzinfo is None:
                last_success = last_success.replace(tzinfo=timezone.utc)
            if last_success is None or now - last_success >= timedelta(
                minutes=source.refresh_interval_minutes
            ):
                due.append(source)
        return due

    @staticmethod
    def list_categories() -> list[TVTheme]:
        return list(db.session.scalars(select(TVTheme).order_by(TVTheme.position, TVTheme.name)))

    def create(self, values: MultiDict, upload: FileStorage | None) -> TVSource:
        prepared = self._prepared(values)
        source = TVSource(**prepared)
        db.session.add(source)
        db.session.flush()
        if source.source_type == "local_file":
            source.local_path = self._save_upload(source, upload)
            source.locator = Path(source.local_path).name
        db.session.commit()
        return source

    def test_configuration(self, values: MultiDict, upload: FileStorage | None) -> dict[str, int]:
        """Validate and test draft values without creating a source record."""
        prepared = self._prepared(values)
        if prepared["source_type"] == "local_file":
            if upload is None or not upload.filename:
                raise TVSourceValidationError("Choose a local M3U file.")
            _validate_m3u_name(upload.filename)
            sample = upload.stream.read(262_144)
            upload.stream.seek(0)
            self._assert_m3u(sample)
            return {"files": 1}
        source = TVSource(**prepared)
        files = self._discover(source, test_only=True)
        if not files:
            raise TVSourceValidationError("No matching M3U files were found.")
        return {"files": len(files)}

    def update(self, source: TVSource, values: MultiDict, upload: FileStorage | None) -> TVSource:
        if source.protected:
            raise TVSourceValidationError(
                "Use the built-in catalogue settings to change its repository."
            )
        prepared = self._prepared(values)
        for key, value in prepared.items():
            setattr(source, key, value)
        if source.source_type == "local_file":
            if upload and upload.filename:
                source.local_path = self._save_upload(source, upload)
                source.locator = Path(source.local_path).name
            elif not source.local_path:
                raise TVSourceValidationError("Choose a local M3U file.")
        else:
            source.local_path = ""
        source.status = "untested"
        source.last_error = ""
        db.session.commit()
        return source

    @staticmethod
    def update_builtin(source: TVSource, values: MultiDict) -> TVSource:
        """Update the configurable GitHub location of the primary IPTV catalogue."""
        if not source.protected:
            raise TVSourceValidationError("This is not the built-in TV catalogue.")

        locator = _repository_slug(str(values.get("locator") or ""))
        branch = str(values.get("branch") or "main").strip() or "main"
        try:
            interval = int(values.get("refresh_interval_minutes") or 360)
        except (TypeError, ValueError) as exc:
            raise TVSourceValidationError("Choose a valid refresh interval.") from exc
        if interval not in REFRESH_INTERVALS:
            raise TVSourceValidationError("Choose a supported refresh interval.")

        source.source_type = "github_repository"
        source.locator = locator
        source.branch = branch[:160]
        source.file_pattern = "*.m3u"
        source.enabled = values.get("enabled") == "on"
        source.auto_refresh = values.get("auto_refresh") == "on"
        source.refresh_interval_minutes = interval
        source.status = "untested"
        source.last_error = ""
        db.session.commit()
        query_cache.invalidate()
        return source

    def test(self, source: TVSource) -> dict[str, int]:
        source.last_tested_at = utc_now()
        try:
            files = self._discover(source, test_only=True)
            if not files:
                raise TVSourceValidationError("No matching M3U files were found.")
            source.status = "healthy"
            source.last_error = ""
            db.session.commit()
            return {"files": len(files)}
        except Exception as exc:
            db.session.rollback()
            failed = db.session.get(TVSource, source.id)
            if failed:
                failed.status = "error"
                failed.last_error = str(exc)[:500]
                failed.last_tested_at = utc_now()
                db.session.commit()
            raise TVSourceValidationError(str(exc)) from exc

    def sync(self, source: TVSource) -> dict[str, int]:
        if not source.enabled:
            raise TVSourceValidationError("Enable this source before refreshing it.")
        if source.protected:
            return self._sync_builtin_source(source)
        try:
            files = self._discover(source)
            if not files:
                raise TVSourceValidationError("No matching M3U files were found.")
            existing = {
                item.github_path: item
                for item in db.session.scalars(
                    select(TVPlaylist).where(TVPlaylist.source_id == source.id)
                )
            }
            active_keys: set[str] = set()
            playlists: list[TVPlaylist] = []
            for item in files:
                key = f"managed/{source.id}/{item['path']}"[:500]
                active_keys.add(key)
                playlist = existing.get(key)
                if playlist is None:
                    playlist = TVPlaylist(
                        source_id=source.id,
                        name=friendly_playlist_name(Path(item["path"]).name),
                        github_path=key,
                        source_url=item["url"],
                    )
                    db.session.add(playlist)
                playlist.name = (
                    source.name
                    if len(files) == 1
                    else friendly_playlist_name(Path(item["path"]).name)
                )
                playlist.source_url = item["url"]
                playlist.source_sha = item["sha"]
                playlist.size_bytes = item["size"]
                playlist.enabled = source.enabled
                playlist.available = True
                playlist.discovered_at = utc_now()
                playlists.append(playlist)
            for key, playlist in existing.items():
                if key not in active_keys:
                    playlist.available = False
            db.session.commit()

            importer = GithubTVSync(session=self.session, timeout_seconds=self.timeout_seconds)
            channels = 0
            for playlist in playlists:
                result = importer.import_playlist(playlist.id, refresh_representatives=False)
                channels += result["channels"]
            importer.refresh_representatives()
            source.status = "healthy"
            source.last_error = ""
            source.last_tested_at = utc_now()
            source.last_success_at = utc_now()
            db.session.commit()
            return {"files": len(playlists), "channels": channels}
        except Exception as exc:
            db.session.rollback()
            failed = db.session.get(TVSource, source.id)
            if failed:
                failed.status = "error"
                failed.last_error = str(exc)[:500]
                failed.last_tested_at = utc_now()
                db.session.commit()
            raise TVSourceValidationError(str(exc)) from exc

    def _sync_builtin_source(self, source: TVSource) -> dict[str, int]:
        """Refresh metadata and only re-import packages backing personal choices."""
        try:
            sync = GithubTVSync(session=self.session, timeout_seconds=self.timeout_seconds)
            discovered = sync.discover(source)
            changed = list(dict.fromkeys([*sync.changed_ids, *sync.pending_ids]))
            selected = relevant_playlist_ids(changed)
            has_imported_catalogue = bool(
                db.session.scalar(
                    select(func.count(TVPlaylist.id)).where(
                        TVPlaylist.source_id == source.id,
                        TVPlaylist.available.is_(True),
                        TVPlaylist.imported.is_(True),
                    )
                )
            )
            initial_import = not has_imported_catalogue
            if not selected and initial_import:
                # The first refresh (or a completely replaced repository) needs
                # a usable catalogue before favorites and ON/OFF choices exist.
                selected = changed
            channels = 0
            for playlist_id in selected:
                result = sync.import_playlist(playlist_id, refresh_representatives=False)
                channels += result["channels"]
            purge_unavailable_playlists(source.id)
            if not initial_import:
                prune_irrelevant_playlist_cache(source.id)
            sync.refresh_representatives()
            refreshed = db.session.get(TVSource, source.id)
            if refreshed:
                refreshed.status = "healthy"
                refreshed.last_error = ""
                refreshed.last_tested_at = utc_now()
                refreshed.last_success_at = utc_now()
                db.session.commit()
            return {
                "files": len(selected),
                "channels": channels,
                "catalog_files": len(discovered),
            }
        except Exception as exc:
            db.session.rollback()
            failed = db.session.get(TVSource, source.id)
            if failed:
                failed.status = "error"
                failed.last_error = str(exc)[:500]
                failed.last_tested_at = utc_now()
                db.session.commit()
            raise TVSourceValidationError(str(exc)) from exc

    @staticmethod
    def toggle(source: TVSource) -> bool:
        source.enabled = not source.enabled
        db.session.execute(
            update(TVPlaylist)
            .where(TVPlaylist.source_id == source.id)
            .values(enabled=source.enabled)
        )
        db.session.commit()
        GithubTVSync.refresh_representatives()
        return source.enabled

    @staticmethod
    def delete(source: TVSource, *, keep_data: bool) -> None:
        if source.protected:
            raise TVSourceValidationError("The built-in catalogue cannot be deleted.")
        local_path = Path(source.local_path) if source.local_path else None
        playlists = list(
            db.session.scalars(select(TVPlaylist).where(TVPlaylist.source_id == source.id))
        )
        if keep_data:
            for playlist in playlists:
                playlist.source_id = None
        else:
            for playlist in playlists:
                db.session.delete(playlist)
        db.session.delete(source)
        db.session.commit()
        if not keep_data and local_path and local_path.is_file():
            local_path.unlink(missing_ok=True)
        GithubTVSync.refresh_representatives()

    @staticmethod
    def update_category(theme: TVTheme, values: MultiDict) -> None:
        name = str(values.get("name") or "").strip()
        if not name:
            raise TVSourceValidationError("Category name is required.")
        theme.name = name[:500]
        theme.enabled = values.get("enabled") == "on"
        persist_theme_preference(theme)
        db.session.commit()
        query_cache.invalidate()

    @staticmethod
    def move_category(theme: TVTheme, direction: str) -> None:
        categories = TVSourceManager.list_categories()
        index = categories.index(theme)
        target_index = index - 1 if direction == "up" else index + 1
        if target_index < 0 or target_index >= len(categories):
            return
        target = categories[target_index]
        theme.position, target.position = target.position, theme.position
        if theme.position == target.position:
            theme.position = target_index
            target.position = index
        db.session.commit()
        query_cache.invalidate()

    @staticmethod
    def merge_category(theme: TVTheme, target: TVTheme) -> None:
        if theme.id == target.id:
            raise TVSourceValidationError("Choose another category to merge into.")
        db.session.execute(
            update(TVGroup).where(TVGroup.theme_id == theme.id).values(theme_id=target.id)
        )
        target.enabled = target.enabled or theme.enabled
        if target.channel_policy is None:
            target.channel_policy = theme.channel_policy
        persist_theme_preference(target)
        source_preference = db.session.get(TVThemePreference, theme.key)
        if source_preference:
            db.session.delete(source_preference)
        target.channel_count += theme.channel_count
        target.group_count += theme.group_count
        db.session.delete(theme)
        db.session.commit()
        query_cache.invalidate()

    def _prepared(self, values: MultiDict) -> dict:
        name = str(values.get("name") or "").strip()
        source_type = str(values.get("source_type") or "")
        locator = str(values.get("locator") or "").strip()
        branch = str(values.get("branch") or "main").strip() or "main"
        pattern = str(values.get("file_pattern") or "*.m3u").strip() or "*.m3u"
        try:
            interval = int(values.get("refresh_interval_minutes") or 360)
        except (TypeError, ValueError) as exc:
            raise TVSourceValidationError("Choose a valid refresh interval.") from exc
        if not name:
            raise TVSourceValidationError("Source name is required.")
        if source_type not in SOURCE_TYPES:
            raise TVSourceValidationError("Choose a supported source type.")
        if interval not in REFRESH_INTERVALS:
            raise TVSourceValidationError("Choose a supported refresh interval.")
        if source_type == "m3u_url":
            try:
                locator = validate_stream_url(locator)
            except UnsafeStreamUrl as exc:
                raise TVSourceValidationError(str(exc)) from exc
        elif source_type == "github_repository":
            locator = _repository_slug(locator)
        elif source_type == "github_file":
            locator = _github_raw_url(locator)
        return {
            "name": name[:240],
            "source_type": source_type,
            "locator": locator[:2000],
            "branch": branch[:160],
            "file_pattern": pattern[:500],
            "enabled": values.get("enabled") == "on",
            "auto_refresh": values.get("auto_refresh") == "on",
            "refresh_interval_minutes": interval,
        }

    def _save_upload(self, source: TVSource, upload: FileStorage | None) -> str:
        if upload is None or not upload.filename:
            raise TVSourceValidationError("Choose a local M3U file.")
        _validate_m3u_name(upload.filename)
        directory = Path(current_app.instance_path) / "tv-source-files"
        directory.mkdir(parents=True, exist_ok=True)
        filename = secure_filename(upload.filename) or "playlist.m3u"
        path = (directory / f"source-{source.id}-{filename}").resolve()
        if directory.resolve() not in path.parents:
            raise TVSourceValidationError("The local filename is invalid.")
        upload.save(path)
        return str(path)

    def _discover(self, source: TVSource, *, test_only: bool = False) -> list[dict]:
        if source.source_type == "github_repository":
            response = self.session.get(
                f"https://api.github.com/repos/{source.locator}/git/trees/{source.branch}",
                params={"recursive": "1"},
                timeout=self.timeout_seconds,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "Dragon-Source-Manager/1.0",
                },
            )
            if response.status_code != 200:
                raise TVSourceValidationError(f"GitHub returned HTTP {response.status_code}.")
            payload = response.json()
            files = []
            for item in payload.get("tree") or []:
                path = str(item.get("path") or "")
                if item.get("type") != "blob" or not fnmatch.fnmatch(path, source.file_pattern):
                    continue
                if not path.casefold().endswith((".m3u", ".m3u8")):
                    continue
                files.append(
                    {
                        "path": path,
                        "url": f"https://raw.githubusercontent.com/{source.locator}/{source.branch}/{path}",
                        "sha": str(item.get("sha") or ""),
                        "size": int(item.get("size") or 0),
                    }
                )
            return files[:500]
        if source.source_type == "local_file":
            path = Path(source.local_path)
            if not path.is_file():
                raise TVSourceValidationError("The uploaded M3U file is missing.")
            sample = path.read_bytes()[:262_144]
            self._assert_m3u(sample)
            return [
                {
                    "path": path.name,
                    "url": str(path),
                    "sha": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "size": path.stat().st_size,
                }
            ]
        url = source.locator if source.source_type == "m3u_url" else _github_raw_url(source.locator)
        response = _public_response(self.session, url, timeout=self.timeout_seconds)
        try:
            if response.status_code != 200:
                raise TVSourceValidationError(f"Source returned HTTP {response.status_code}.")
            sample = next(response.iter_content(chunk_size=262_144), b"")
            self._assert_m3u(sample)
            size = int(response.headers.get("Content-Length") or len(sample))
            digest = (
                response.headers.get("ETag", "").strip('"') or hashlib.sha256(sample).hexdigest()
            )
        finally:
            response.close()
        return [
            {
                "path": Path(urlsplit(url).path).name or "playlist.m3u",
                "url": url,
                "sha": digest,
                "size": size,
            }
        ]

    @staticmethod
    def _assert_m3u(sample: bytes) -> None:
        text = sample.decode("utf-8-sig", "replace")
        if "#EXTM3U" not in text[:2000] and "#EXTINF" not in text:
            raise TVSourceValidationError("The source did not return a valid M3U playlist.")
