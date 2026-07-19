from __future__ import annotations

import atexit
import base64
import binascii
import json
import os
import re
import shutil
import subprocess
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from app.shared.ids import new_id

TORRENT_METADATA_HOSTS = {"yts.bz", "yts.gg"}
MAX_TORRENT_METADATA_BYTES = 2 * 1024 * 1024
INFO_HASH_PATTERN = re.compile(r"^[a-fA-F0-9]{40}$|^[A-Z2-7a-z2-7]{32}$")
DIRECT_PLAYBACK_SUFFIXES = {".mp4", ".m4v", ".webm"}
TRANSCODE_PLAYBACK_SUFFIXES = {".mkv", ".mov", ".avi", ".ts", ".m2ts", ".mpg", ".mpeg"}
TRANSCODE_CODEC_PATTERN = re.compile(
    r"(?i)(?:^|[._\-\s])(?:x265|h265|h\.265|hevc|hi10p|10\s*-?\s*bit)(?:$|[._\-\s])"
)


class PlaybackRuntimeError(RuntimeError):
    pass


class WebTorrentClient:
    """Small JSON control channel. Media bytes never cross this process pipe."""

    def __init__(self, *, project_root: Path, helper_path: Path) -> None:
        self.project_root = project_root
        self.helper_path = helper_path
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._counter = 0

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        node = shutil.which("node")
        if not node:
            raise PlaybackRuntimeError("Node.js is required for local magnet playback.")
        self._process = subprocess.Popen(  # noqa: S603 - trusted executable and helper
            [node, str(self.helper_path)],
            cwd=self.project_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        return self._process

    def request(self, command: str, **payload: object) -> dict:
        with self._lock:
            process = self._ensure_process()
            if process.stdin is None or process.stdout is None:
                raise PlaybackRuntimeError("WebTorrent runtime pipes are unavailable.")
            self._counter += 1
            request_id = str(self._counter)
            message = {"id": request_id, "command": command, **payload}
            try:
                process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
                process.stdin.flush()
                line = process.stdout.readline()
            except (BrokenPipeError, OSError) as exc:
                raise PlaybackRuntimeError("WebTorrent runtime stopped unexpectedly.") from exc
            if not line:
                raise PlaybackRuntimeError("WebTorrent runtime stopped unexpectedly.")
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PlaybackRuntimeError("WebTorrent runtime returned invalid data.") from exc
            if response.get("id") != request_id:
                raise PlaybackRuntimeError("WebTorrent runtime response was out of sequence.")
            if not response.get("ok"):
                raise PlaybackRuntimeError(str(response.get("error") or "Local playback failed."))
            result = response.get("result")
            return result if isinstance(result, dict) else {}

    def terminate(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            if process is None or process.poll() is not None:
                return
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@dataclass
class PlaybackSession:
    id: str
    movie_id: str
    user_id: str
    source_id: str
    cache_key: str
    root: Path
    target_season: int | None = None
    target_episode: int | None = None
    cache_hit: bool = False
    state: str = "metadata"
    message: str = "Reading torrent metadata…"
    file_name: str = ""
    total_bytes: int = 0
    downloaded_bytes: int = 0
    file_progress: float = 0.0
    buffer_percent: int = 0
    complete: bool = False
    peers: int = 0
    download_speed: int = 0
    stream_url: str = ""
    startup_timings: dict[str, int | None] = field(default_factory=dict)
    runtime_started: bool = False
    stopped: bool = False
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _magnet_info_hash(magnet: str) -> str:
    if not magnet.startswith("magnet:?"):
        raise PlaybackRuntimeError("This local source is not a valid magnet.")
    values = parse_qs(urlparse(magnet).query).get("xt", [])
    for value in values:
        prefix = "urn:btih:"
        if value.lower().startswith(prefix):
            candidate = value[len(prefix) :]
            if INFO_HASH_PATTERN.fullmatch(candidate):
                if len(candidate) == 32:
                    try:
                        return base64.b32decode(candidate.upper()).hex()
                    except (binascii.Error, ValueError):
                        continue
                return candidate.lower()
    raise PlaybackRuntimeError("This magnet does not contain a valid BitTorrent info hash.")


def _tree_size(path: Path) -> int:
    total = 0
    if path.is_file():
        with suppress(OSError):
            return path.stat().st_size
        return 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        if item.is_file():
            with suppress(OSError):
                total += item.stat().st_size
    return total


def _stream_kind(file_name: str) -> str:
    name = str(file_name or "")
    suffix = Path(name).suffix.lower()
    if suffix in DIRECT_PLAYBACK_SUFFIXES and TRANSCODE_CODEC_PATTERN.search(name):
        return "transcode"
    if suffix in DIRECT_PLAYBACK_SUFFIXES:
        return "direct"
    if suffix in TRANSCODE_PLAYBACK_SUFFIXES:
        return "transcode"
    return "unknown"


class MagnetPlaybackManager:
    def __init__(
        self,
        *,
        cache_root: Path,
        client: WebTorrentClient,
        cache_limit_gb: int = 10,
        cache_ttl_hours: int = 168,
    ) -> None:
        self.cache_root = cache_root.resolve()
        self.torrent_root = self.cache_root / "torrents"
        self.metadata_root = self.cache_root / "metadata"
        self.torrent_root.mkdir(parents=True, exist_ok=True)
        self.metadata_root.mkdir(parents=True, exist_ok=True)
        self.cache_limit_bytes = cache_limit_gb * 1024**3
        self.cache_ttl_hours = cache_ttl_hours
        self.client = client
        self._sessions: dict[str, PlaybackSession] = {}
        self._lock = threading.RLock()
        self.cleanup_cache()

    def start(
        self,
        *,
        movie_id: str,
        user_id: str,
        source_id: str,
        magnet: str,
        torrent_url: str = "",
        origin: str,
        season: int | None = None,
        episode: int | None = None,
    ) -> dict:
        cache_key = _magnet_info_hash(magnet)
        parsed_origin = urlparse(origin)
        if (
            parsed_origin.scheme not in {"http", "https"}
            or parsed_origin.hostname not in {"127.0.0.1", "localhost"}
            or parsed_origin.username
            or parsed_origin.password
        ):
            raise PlaybackRuntimeError("Local playback requires a loopback application origin.")
        session_id = new_id("play")
        root = (self.torrent_root / cache_key).resolve()
        root.relative_to(self.torrent_root)
        metadata_path = self.metadata_root / f"{cache_key}.torrent"
        cache_hit = metadata_path.is_file() or _tree_size(root) > 0
        session = PlaybackSession(
            id=session_id,
            movie_id=movie_id,
            user_id=user_id,
            source_id=source_id,
            cache_key=cache_key,
            root=root,
            target_season=season,
            target_episode=episode,
            cache_hit=cache_hit,
        )
        with self._lock:
            self._sessions[session_id] = session
        threading.Thread(
            target=self._prepare,
            args=(session_id, magnet, torrent_url, origin.rstrip("/")),
            daemon=True,
            name=f"dragon-playback-{session_id[-8:]}",
        ).start()
        return self.public_status(session)

    def _prepare(self, session_id: str, magnet: str, torrent_url: str, origin: str) -> None:
        started_at = time.monotonic()
        try:
            session = self._get(session_id)
            torrent_file = (
                self._torrent_metadata(torrent_url, session.cache_key)
                if torrent_url
                else self._cached_metadata(session.cache_key)
            )
            session.root.mkdir(parents=True, exist_ok=True)
            with suppress(OSError):
                os.utime(session.root)
            result = self.client.request(
                "start",
                sessionId=session_id,
                magnet=magnet,
                cacheKey=session.cache_key,
                cacheRoot=str(self.cache_root),
                root=str(session.root),
                torrentFile=str(torrent_file) if torrent_file else "",
                origin=origin,
                season=session.target_season,
                episode=session.target_episode,
            )
            with self._lock:
                session = self._get(session_id)
                if session.stopped:
                    self.client.request("close", sessionId=session_id)
                    return
                session.runtime_started = True
                session.startup_timings.setdefault(
                    "control_ready_ms", int((time.monotonic() - started_at) * 1000)
                )
                self._apply_runtime_status(session, result)
        except PlaybackRuntimeError as exc:
            with self._lock:
                session = self._sessions.get(session_id)
                if session is not None and not session.stopped:
                    session.state = "failed"
                    session.message = str(exc)
                    session.updated_at = datetime.now(UTC)

    def _cached_metadata(self, cache_key: str) -> Path | None:
        path = self.metadata_root / f"{cache_key}.torrent"
        try:
            if (
                path.is_file()
                and path.stat().st_size <= MAX_TORRENT_METADATA_BYTES
                and path.read_bytes()[:1] == b"d"
            ):
                os.utime(path)
                return path
        except OSError:
            pass
        path.unlink(missing_ok=True)
        return None

    def _torrent_metadata(self, url: str, cache_key: str) -> Path:
        cached = self._cached_metadata(cache_key)
        if cached is not None:
            return cached
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in TORRENT_METADATA_HOSTS:
            raise PlaybackRuntimeError("The paired torrent metadata source is not trusted.")
        destination = self.metadata_root / f"{cache_key}.torrent"
        request = Request(url, headers={"User-Agent": "DragonV2/1.0"})  # noqa: S310
        try:
            with urlopen(request, timeout=20) as response:  # noqa: S310 - allowlisted URL
                final = urlparse(response.geturl())
                if final.scheme != "https" or final.hostname not in TORRENT_METADATA_HOSTS:
                    raise PlaybackRuntimeError("Torrent metadata redirected to an untrusted host.")
                payload = response.read(MAX_TORRENT_METADATA_BYTES + 1)
        except (OSError, ValueError) as exc:
            raise PlaybackRuntimeError("Torrent metadata could not be downloaded.") from exc
        if len(payload) > MAX_TORRENT_METADATA_BYTES or not payload.startswith(b"d"):
            raise PlaybackRuntimeError("Torrent metadata is invalid.")
        temporary = destination.with_suffix(".torrent.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, destination)
        return destination

    def _get(self, session_id: str) -> PlaybackSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise PlaybackRuntimeError("Playback session was not found.")
        return session

    @staticmethod
    def _owns(session: PlaybackSession, *, user_id: str, movie_id: str | None = None) -> None:
        if session.user_id != user_id or (
            movie_id is not None and session.movie_id != movie_id
        ):
            raise PlaybackRuntimeError("Playback session was not found.")

    def _apply_runtime_status(self, session: PlaybackSession, result: dict) -> None:
        session.file_name = str(result.get("fileName") or "")
        session.total_bytes = max(0, int(result.get("totalBytes") or 0))
        session.downloaded_bytes = max(0, int(result.get("downloadedBytes") or 0))
        session.file_progress = min(1.0, max(0.0, float(result.get("fileProgress") or 0)))
        session.buffer_percent = min(100, max(0, int(result.get("bufferPercent") or 0)))
        session.complete = bool(result.get("complete"))
        session.peers = max(0, int(result.get("peers") or 0))
        session.download_speed = max(0, int(result.get("downloadSpeed") or 0))
        session.stream_url = str(result.get("streamUrl") or "")
        timings = result.get("timings")
        if isinstance(timings, dict):
            for key, value in timings.items():
                session.startup_timings[str(key)] = int(value) if value is not None else None
        error = str(result.get("error") or "").strip()
        if error:
            session.state = "failed"
            session.message = error
        elif session.stream_url and session.file_name and session.total_bytes:
            session.state = "ready"
            stream_kind = _stream_kind(session.file_name)
            if stream_kind == "transcode":
                session.message = "Stream ready; local transcoding is required for this file."
            elif session.peers:
                session.message = "Stream ready; the browser is buffering directly from peers."
            else:
                session.message = "Stream ready; waiting for torrent peers or cached pieces."
        else:
            session.state = "metadata"
            session.message = "Selecting the best video file from this torrent…"
        session.updated_at = datetime.now(UTC)

    def status(self, session_id: str, *, user_id: str) -> dict:
        with self._lock:
            session = self._get(session_id)
            self._owns(session, user_id=user_id)
            should_refresh = session.runtime_started and session.state not in {"failed", "stopped"}
        if should_refresh:
            try:
                result = self.client.request("status", sessionId=session_id)
                with self._lock:
                    session = self._get(session_id)
                    self._owns(session, user_id=user_id)
                    self._apply_runtime_status(session, result)
            except PlaybackRuntimeError as exc:
                with self._lock:
                    session = self._get(session_id)
                    session.state = "failed"
                    session.message = str(exc)
        with self._lock:
            return self.public_status(self._get(session_id))

    @staticmethod
    def public_status(session: PlaybackSession) -> dict:
        return {
            "id": session.id,
            "state": session.state,
            "message": session.message,
            "file_name": session.file_name,
            "stream_url": session.stream_url or None,
            "stream_kind": _stream_kind(session.file_name),
            "target_season": session.target_season,
            "target_episode": session.target_episode,
            "buffer_percent": session.buffer_percent,
            "file_progress": round(session.file_progress, 4),
            "downloaded_bytes": session.downloaded_bytes,
            "total_bytes": session.total_bytes,
            "peers": session.peers,
            "download_speed": session.download_speed,
            "cache_hit": session.cache_hit,
            "startup_timings": dict(session.startup_timings),
            "complete": session.complete,
        }

    def stop(self, session_id: str, *, user_id: str) -> None:
        with self._lock:
            session = self._get(session_id)
            self._owns(session, user_id=user_id)
            session.stopped = True
            session.state = "stopped"
            session.message = "Local playback stopped. Cached pieces were kept."
            runtime_started = session.runtime_started
        if runtime_started:
            with suppress(PlaybackRuntimeError):
                self.client.request("close", sessionId=session_id)
        self.cleanup_cache()

    def _active_cache_keys(self) -> set[str]:
        with self._lock:
            return {
                session.cache_key
                for session in self._sessions.values()
                if not session.stopped and session.state != "failed"
            }

    def _cache_entries(self) -> list[dict[str, object]]:
        keys = {item.name for item in self.torrent_root.iterdir() if item.is_dir()}
        keys.update(item.stem for item in self.metadata_root.glob("*.torrent"))
        entries: list[dict[str, object]] = []
        for key in keys:
            data_path = self.torrent_root / key
            metadata_path = self.metadata_root / f"{key}.torrent"
            paths = [item for item in (data_path, metadata_path) if item.exists()]
            if not paths:
                continue
            modified = max(item.stat().st_mtime for item in paths)
            entries.append(
                {
                    "key": key,
                    "data_path": data_path,
                    "metadata_path": metadata_path,
                    "bytes": sum(_tree_size(item) for item in paths),
                    "modified": modified,
                }
            )
        return entries

    @staticmethod
    def _remove_entry(entry: dict[str, object]) -> None:
        shutil.rmtree(entry["data_path"], ignore_errors=True)  # type: ignore[arg-type]
        Path(entry["metadata_path"]).unlink(missing_ok=True)  # type: ignore[arg-type]

    def cleanup_cache(self, *, clear_all_inactive: bool = False) -> dict:
        active = self._active_cache_keys()
        entries = self._cache_entries()
        cutoff = datetime.now(UTC) - timedelta(hours=self.cache_ttl_hours)
        removed_bytes = 0
        for entry in entries:
            if entry["key"] in active:
                continue
            expired = datetime.fromtimestamp(float(entry["modified"]), UTC) < cutoff
            if clear_all_inactive or expired:
                removed_bytes += int(entry["bytes"])
                self._remove_entry(entry)
        entries = self._cache_entries()
        used = sum(int(entry["bytes"]) for entry in entries)
        for entry in sorted(entries, key=lambda value: float(value["modified"])):
            if used <= self.cache_limit_bytes:
                break
            if entry["key"] in active:
                continue
            size = int(entry["bytes"])
            self._remove_entry(entry)
            used -= size
            removed_bytes += size
        return {**self.cache_status(), "removed_bytes": removed_bytes}

    def clear_inactive_cache(self) -> dict:
        return self.cleanup_cache(clear_all_inactive=True)

    def cache_status(self) -> dict:
        entries = self._cache_entries()
        active = self._active_cache_keys()
        return {
            "used_bytes": sum(int(entry["bytes"]) for entry in entries),
            "limit_bytes": self.cache_limit_bytes,
            "ttl_hours": self.cache_ttl_hours,
            "entries": len(entries),
            "active_entries": sum(entry["key"] in active for entry in entries),
        }


def build_playback_manager(
    *,
    instance_path: str,
    cache_limit_gb: int = 10,
    cache_ttl_hours: int = 168,
) -> MagnetPlaybackManager:
    helper_path = Path(__file__).with_name("webtorrent-helper.mjs").resolve()
    project_root = helper_path.parents[2]
    client = WebTorrentClient(project_root=project_root, helper_path=helper_path)
    atexit.register(client.terminate)
    return MagnetPlaybackManager(
        cache_root=Path(instance_path) / "playback-cache",
        client=client,
        cache_limit_gb=cache_limit_gb,
        cache_ttl_hours=cache_ttl_hours,
    )
