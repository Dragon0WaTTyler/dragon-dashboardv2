from __future__ import annotations

import atexit
import base64
import binascii
import json
import mimetypes
import shutil
import subprocess
import threading
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.shared.ids import new_id

STREAM_CHUNK_BYTES = 256 * 1024
STREAM_RESPONSE_BYTES = 2 * 1024 * 1024
TORRENT_METADATA_HOSTS = {"yts.bz", "yts.gg"}


class PlaybackRuntimeError(RuntimeError):
    pass


class PlaybackNotReady(PlaybackRuntimeError):
    pass


class WebTorrentClient:
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
        self._process = subprocess.Popen(  # noqa: S603 - executable and helper are trusted paths
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
    root: Path
    state: str = "preparing"
    message: str = "Reading torrent metadata…"
    file_name: str = ""
    total_bytes: int = 0
    complete: bool = False
    peers: int = 0
    download_speed: int = 0
    runtime_started: bool = False
    stopped: bool = False
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class StreamRange:
    start: int
    end: int
    total: int
    mime_type: str

    @property
    def length(self) -> int:
        return self.end - self.start + 1


class MagnetPlaybackManager:
    def __init__(self, *, cache_root: Path, client: WebTorrentClient) -> None:
        self.cache_root = cache_root.resolve()
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.client = client
        self._sessions: dict[str, PlaybackSession] = {}
        self._lock = threading.RLock()

    def start(
        self,
        *,
        movie_id: str,
        user_id: str,
        source_id: str,
        magnet: str,
        torrent_url: str = "",
    ) -> dict:
        if not magnet.startswith("magnet:?"):
            raise PlaybackRuntimeError("This local source is not a valid magnet.")
        session_id = new_id("play")
        root = (self.cache_root / session_id).resolve()
        root.relative_to(self.cache_root)
        session = PlaybackSession(
            id=session_id,
            movie_id=movie_id,
            user_id=user_id,
            source_id=source_id,
            root=root,
        )
        with self._lock:
            self._sessions[session_id] = session
        threading.Thread(
            target=self._prepare,
            args=(session_id, magnet, torrent_url),
            daemon=True,
            name=f"dragon-playback-{session_id[-8:]}",
        ).start()
        return self.public_status(session)

    def _prepare(self, session_id: str, magnet: str, torrent_url: str) -> None:
        try:
            torrent_file = self._download_torrent_file(
                torrent_url, self._get(session_id).root
            ) if torrent_url else None
            result = self.client.request(
                "start",
                sessionId=session_id,
                magnet=magnet,
                root=str(self._get(session_id).root),
                torrentFile=str(torrent_file) if torrent_file else "",
            )
            with self._lock:
                session = self._get(session_id)
                if session.stopped:
                    self.client.request("close", sessionId=session_id)
                    return
                session.runtime_started = True
                self._apply_runtime_status(session, result)
        except PlaybackRuntimeError as exc:
            with self._lock:
                session = self._sessions.get(session_id)
                if session is not None and not session.stopped:
                    session.state = "failed"
                    session.message = str(exc)
                    session.updated_at = datetime.now(UTC)
        finally:
            with self._lock:
                session = self._sessions.get(session_id)
                stopped_root = session.root if session is not None and session.stopped else None
            if stopped_root is not None:
                shutil.rmtree(stopped_root, ignore_errors=True)

    @staticmethod
    def _download_torrent_file(url: str, root: Path) -> Path:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in TORRENT_METADATA_HOSTS:
            raise PlaybackRuntimeError("The paired torrent metadata source is not trusted.")
        root.mkdir(parents=True, exist_ok=True)
        destination = root / "source.torrent"
        request = Request(  # noqa: S310 - URL is allowlisted above
            url, headers={"User-Agent": "DragonV2/1.0"}
        )
        try:
            with urlopen(request, timeout=20) as response:  # noqa: S310 - URL is allowlisted
                final = urlparse(response.geturl())
                if final.scheme != "https" or final.hostname not in TORRENT_METADATA_HOSTS:
                    raise PlaybackRuntimeError("Torrent metadata redirected to an untrusted host.")
                payload = response.read(2 * 1024 * 1024 + 1)
        except (OSError, ValueError) as exc:
            raise PlaybackRuntimeError("Torrent metadata could not be downloaded.") from exc
        if len(payload) > 2 * 1024 * 1024 or not payload.startswith(b"d"):
            raise PlaybackRuntimeError("Torrent metadata is invalid.")
        destination.write_bytes(payload)
        return destination

    def _get(self, session_id: str) -> PlaybackSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise PlaybackRuntimeError("Playback session was not found.")
        return session

    @staticmethod
    def _owns(session: PlaybackSession, *, user_id: str, movie_id: str | None = None) -> None:
        if session.user_id != user_id or (movie_id is not None and session.movie_id != movie_id):
            raise PlaybackRuntimeError("Playback session was not found.")

    def _apply_runtime_status(self, session: PlaybackSession, result: dict) -> None:
        session.file_name = str(result.get("fileName") or "")
        session.total_bytes = max(0, int(result.get("totalBytes") or 0))
        session.complete = bool(result.get("complete"))
        session.peers = max(0, int(result.get("peers") or 0))
        session.download_speed = max(0, int(result.get("downloadSpeed") or 0))
        error = str(result.get("error") or "").strip()
        if error:
            session.state = "failed"
            session.message = error
        elif result.get("directStream") and session.file_name and session.total_bytes:
            session.state = "ready"
            session.message = "Local stream is ready. The player can request torrent pieces."
        else:
            session.state = "preparing"
            session.message = "Selecting a browser-compatible movie file…"
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
            "buffer_percent": 100 if session.complete else 0,
            "peers": session.peers,
            "download_speed": session.download_speed,
            "complete": session.complete,
        }

    def open_range(self, session_id: str, *, user_id: str, range_header: str) -> StreamRange:
        self.status(session_id, user_id=user_id)
        with self._lock:
            session = self._get(session_id)
            self._owns(session, user_id=user_id)
            if session.state == "failed":
                raise PlaybackRuntimeError(session.message)
            if session.state != "ready" or not session.total_bytes:
                raise PlaybackNotReady("The local stream is still preparing.")
            start, requested_end = self._parse_range(range_header, session.total_bytes)
            end = min(requested_end, start + STREAM_RESPONSE_BYTES - 1)
            mime_type = mimetypes.guess_type(session.file_name)[0] or "video/mp4"
            return StreamRange(start, end, session.total_bytes, mime_type)

    def read_chunk(
        self, session_id: str, *, user_id: str, start: int, end: int
    ) -> bytes:
        with self._lock:
            session = self._get(session_id)
            self._owns(session, user_id=user_id)
            if session.state != "ready":
                raise PlaybackNotReady("The local stream is not ready.")
        result = self.client.request(
            "read", sessionId=session_id, start=start, end=end
        )
        encoded = str(result.get("data") or "")
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise PlaybackRuntimeError("WebTorrent returned invalid stream data.") from exc
        if len(payload) != end - start + 1:
            raise PlaybackRuntimeError("WebTorrent returned an incomplete byte range.")
        return payload

    @staticmethod
    def _parse_range(value: str, total: int) -> tuple[int, int]:
        if not value:
            return 0, total - 1
        if not value.startswith("bytes=") or "," in value:
            raise PlaybackRuntimeError("Unsupported byte range.")
        start_text, separator, end_text = value[6:].partition("-")
        if not separator:
            raise PlaybackRuntimeError("Invalid byte range.")
        try:
            if not start_text:
                length = int(end_text)
                if length <= 0:
                    raise ValueError
                return max(0, total - length), total - 1
            start = int(start_text)
            end = int(end_text) if end_text else total - 1
        except ValueError as exc:
            raise PlaybackRuntimeError("Invalid byte range.") from exc
        if start < 0 or start >= total or end < start:
            raise PlaybackRuntimeError("Requested byte range is outside the movie.")
        return start, min(end, total - 1)

    def stop(self, session_id: str, *, user_id: str) -> None:
        with self._lock:
            session = self._get(session_id)
            self._owns(session, user_id=user_id)
            session.stopped = True
            session.state = "stopped"
            runtime_started = session.runtime_started
        if runtime_started:
            with suppress(PlaybackRuntimeError):
                self.client.request("close", sessionId=session_id)
        shutil.rmtree(session.root, ignore_errors=True)


def build_playback_manager(*, instance_path: str) -> MagnetPlaybackManager:
    helper_path = Path(__file__).with_name("webtorrent-helper.mjs").resolve()
    project_root = helper_path.parents[2]
    client = WebTorrentClient(project_root=project_root, helper_path=helper_path)
    atexit.register(client.terminate)
    return MagnetPlaybackManager(
        cache_root=Path(instance_path) / "playback-cache",
        client=client,
    )
