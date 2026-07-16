from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone

import requests

from app.db import connect_db
from app.services.m3u import parse_m3u


GITHUB_API = "https://api.github.com"


class SyncError(RuntimeError):
    pass


class GithubPlaylistSync:
    def __init__(self, config: dict):
        self.owner = config["MYTV_GITHUB_OWNER"]
        self.repo = config["MYTV_GITHUB_REPO"]
        self.branch = config["MYTV_GITHUB_BRANCH"]
        self.database = config["DATABASE"]
        self.timeout = config["MYTV_HTTP_TIMEOUT"]
        self.max_channels = config["MYTV_MAX_CHANNELS_PER_PLAYLIST"]
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "User-Agent": "My-TV-Flask-Dashboard/1.0",
            }
        )

    def discover(self) -> list[int]:
        url = f"{GITHUB_API}/repos/{self.owner}/{self.repo}/contents"
        response = self.session.get(
            url,
            params={"ref": self.branch},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise SyncError(f"GitHub returned HTTP {response.status_code}")

        files = sorted([
            item
            for item in response.json()
            if item.get("type") == "file" and item.get("name", "").lower().endswith(".m3u")
        ], key=lambda item: item.get("name", ""))
        connection = connect_db(self.database)
        playlist_ids: list[int] = []
        try:
            connection.execute("UPDATE playlists SET available = 0")
            for item in files:
                connection.execute(
                    """
                    INSERT INTO playlists(name, github_path, source_url, sha, size_bytes, available)
                    VALUES (?, ?, ?, ?, ?, 1)
                    ON CONFLICT(github_path) DO UPDATE SET
                        name = excluded.name,
                        source_url = excluded.source_url,
                        sha = excluded.sha,
                        size_bytes = excluded.size_bytes,
                        available = 1,
                        discovered_at = CURRENT_TIMESTAMP
                    """,
                    (
                        friendly_playlist_name(item["name"]),
                        item["path"],
                        item["download_url"],
                        item.get("sha"),
                        int(item.get("size") or 0),
                    ),
                )
                row = connection.execute(
                    "SELECT id FROM playlists WHERE github_path = ?", (item["path"],)
                ).fetchone()
                playlist_ids.append(row["id"])
            connection.commit()
            return playlist_ids
        finally:
            connection.close()

    def import_playlist(self, playlist_id: int, progress=None) -> dict:
        connection = connect_db(self.database)
        playlist = connection.execute(
            "SELECT * FROM playlists WHERE id = ?", (playlist_id,)
        ).fetchone()
        if not playlist:
            connection.close()
            raise SyncError(f"Playlist {playlist_id} does not exist")

        connection.execute(
            "UPDATE playlists SET sync_status = 'syncing', sync_error = NULL WHERE id = ?",
            (playlist_id,),
        )
        connection.commit()

        token = uuid.uuid4().hex
        group_ids = {
            row["name"]: row["id"]
            for row in connection.execute(
                "SELECT id, name FROM channel_groups WHERE playlist_id = ?", (playlist_id,)
            )
        }
        count = 0
        position = 0
        batch: list[tuple] = []

        try:
            with self.session.get(
                playlist["source_url"],
                stream=True,
                timeout=(self.timeout, max(60, self.timeout * 6)),
            ) as response:
                if response.status_code != 200:
                    raise SyncError(f"Playlist download returned HTTP {response.status_code}")

                response.encoding = response.encoding or "utf-8"
                for entry in parse_m3u(response.iter_lines(decode_unicode=True)):
                    if self.max_channels and count >= self.max_channels:
                        break
                    group_id = group_ids.get(entry.group)
                    if group_id is None:
                        connection.execute(
                            """
                            INSERT INTO channel_groups(playlist_id, name)
                            VALUES (?, ?)
                            ON CONFLICT(playlist_id, name) DO NOTHING
                            """,
                            (playlist_id, entry.group),
                        )
                        row = connection.execute(
                            "SELECT id FROM channel_groups WHERE playlist_id = ? AND name = ?",
                            (playlist_id, entry.group),
                        ).fetchone()
                        group_id = row["id"]
                        group_ids[entry.group] = group_id

                    position += 1
                    batch.append(
                        (
                            playlist_id,
                            group_id,
                            entry.external_key,
                            entry.name,
                            entry.tvg_id,
                            entry.tvg_name,
                            entry.logo_url,
                            entry.url,
                            entry.kind,
                            position,
                            token,
                        )
                    )
                    count += 1
                    if len(batch) >= 500:
                        self._flush_channels(connection, batch)
                        batch.clear()
                        if progress:
                            progress(count)

            if batch:
                self._flush_channels(connection, batch)

            connection.execute(
                "DELETE FROM channels WHERE playlist_id = ? AND last_seen_sync <> ?",
                (playlist_id, token),
            )
            stored_count = connection.execute(
                "SELECT COUNT(*) AS amount FROM channels WHERE playlist_id = ?",
                (playlist_id,),
            ).fetchone()["amount"]
            connection.execute(
                """
                UPDATE channel_groups
                SET channel_count = (
                    SELECT COUNT(*) FROM channels WHERE channels.group_id = channel_groups.id
                )
                WHERE playlist_id = ?
                """,
                (playlist_id,),
            )
            connection.execute(
                "DELETE FROM channel_groups WHERE playlist_id = ? AND channel_count = 0",
                (playlist_id,),
            )
            group_count = connection.execute(
                "SELECT COUNT(*) AS amount FROM channel_groups WHERE playlist_id = ?",
                (playlist_id,),
            ).fetchone()["amount"]
            connection.execute(
                """
                UPDATE playlists
                SET imported = 1,
                    channel_count = ?,
                    group_count = ?,
                    sync_status = 'ready',
                    sync_error = NULL,
                    last_synced_at = ?
                WHERE id = ?
                """,
                (
                    stored_count,
                    group_count,
                    datetime.now(timezone.utc).isoformat(),
                    playlist_id,
                ),
            )
            connection.commit()
            return {
                "playlist_id": playlist_id,
                "channels": stored_count,
                "groups": group_count,
                "parsed_channels": count,
            }
        except Exception as error:
            connection.rollback()
            connection.execute(
                "UPDATE playlists SET sync_status = 'error', sync_error = ? WHERE id = ?",
                (str(error)[:500], playlist_id),
            )
            connection.commit()
            raise
        finally:
            connection.close()

    @staticmethod
    def _flush_channels(connection, rows: list[tuple]) -> None:
        connection.executemany(
            """
            INSERT INTO channels(
                playlist_id, group_id, external_key, name, tvg_id, tvg_name,
                logo_url, stream_url, stream_kind, position, last_seen_sync
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(playlist_id, external_key) DO UPDATE SET
                group_id = excluded.group_id,
                name = excluded.name,
                tvg_id = excluded.tvg_id,
                tvg_name = excluded.tvg_name,
                logo_url = excluded.logo_url,
                stream_url = excluded.stream_url,
                stream_kind = excluded.stream_kind,
                position = excluded.position,
                last_seen_sync = excluded.last_seen_sync
            """,
            rows,
        )


class SyncCoordinator:
    def __init__(self):
        self._lock = threading.Lock()
        self._status = {
            "state": "idle",
            "mode": None,
            "message": "Ready",
            "current": 0,
            "total": 0,
            "channels": 0,
            "error": None,
            "started_at": None,
            "finished_at": None,
        }

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def start(self, app, mode: str, playlist_ids: list[int] | None = None) -> bool:
        with self._lock:
            if self._status["state"] == "running":
                return False
            self._status.update(
                {
                    "state": "running",
                    "mode": mode,
                    "message": "Connecting to source…",
                    "current": 0,
                    "total": 0,
                    "channels": 0,
                    "error": None,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "finished_at": None,
                }
            )
        thread = threading.Thread(
            target=self._run,
            args=(app, mode, playlist_ids or []),
            daemon=True,
            name="mytv-sync",
        )
        thread.start()
        return True

    def _run(self, app, mode: str, playlist_ids: list[int]) -> None:
        try:
            syncer = GithubPlaylistSync(app.config)
            discovered_ids = syncer.discover()
            if mode == "catalog":
                selected = []
            elif mode == "all":
                selected = discovered_ids
            elif mode == "selected":
                selected = [item for item in playlist_ids if item in discovered_ids]
            else:
                limit = max(1, int(app.config["MYTV_IMPORT_LIMIT"]))
                selected = discovered_ids[-limit:]

            with self._lock:
                self._status["total"] = len(selected)
                self._status["message"] = (
                    f"Found {len(discovered_ids)} playlists"
                    if not selected
                    else f"Importing {len(selected)} playlists…"
                )

            total_channels = 0
            for index, playlist_id in enumerate(selected, start=1):
                with self._lock:
                    self._status["current"] = index
                    self._status["message"] = f"Importing playlist {index} of {len(selected)}"

                def update_progress(count):
                    with self._lock:
                        self._status["channels"] = total_channels + count

                result = syncer.import_playlist(playlist_id, update_progress)
                total_channels += result["channels"]
                with self._lock:
                    self._status["channels"] = total_channels

            with self._lock:
                self._status.update(
                    {
                        "state": "complete",
                        "message": (
                            "Source catalogue refreshed"
                            if not selected
                            else f"Imported {total_channels:,} channels"
                        ),
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
        except Exception as error:
            with self._lock:
                self._status.update(
                    {
                        "state": "error",
                        "message": "Sync failed",
                        "error": str(error),
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                    }
                )


def friendly_playlist_name(filename: str) -> str:
    parts = filename.rsplit("_Hunter_", 1)
    if len(parts) == 2:
        stamp = parts[0].replace("FIW_", "").split("_", 1)[0]
        package_code = parts[1].removesuffix(".m3u")
        try:
            timestamp = int(stamp)
            date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%d %b · %H:%M")
            return f"Package {package_code} · {date}"
        except (ValueError, OSError):
            pass
    return filename.removesuffix(".m3u").replace("_", " ")


sync_coordinator = SyncCoordinator()
