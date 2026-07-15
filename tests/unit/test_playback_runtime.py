from __future__ import annotations

import time
from pathlib import Path

from app.playback.runtime import MagnetPlaybackManager


class FakeWebTorrentClient:
    def __init__(self, *, unsafe_path: Path | None = None) -> None:
        self.unsafe_path = unsafe_path
        self.results: dict[str, dict] = {}

    def request(self, command: str, **payload: object) -> dict:
        session_id = str(payload["sessionId"])
        if command == "close":
            return {"closed": True}
        if command == "start":
            root = Path(str(payload["root"]))
            root.mkdir(parents=True, exist_ok=True)
            media = self.unsafe_path or root / "movie.mp4"
            media.write_bytes(b"dragon-video")
            result = {
                "filePath": str(media),
                "fileName": "movie.mp4",
                "totalBytes": len(b"dragon-video"),
                "sequentialBytes": len(b"dragon-video"),
                "tailStart": 0,
                "tailReady": True,
                "complete": True,
                "peers": 2,
                "downloadSpeed": 1024,
                "error": "",
            }
            self.results[session_id] = result
            return result
        return self.results[session_id]


def wait_until_ready(manager: MagnetPlaybackManager, session_id: str) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        status = manager.status(session_id, user_id="user-1")
        if status["state"] != "preparing":
            return status
        time.sleep(0.01)
    raise AssertionError("playback session did not finish preparing")


def test_manager_prepares_owned_range_and_cleans_up(tmp_path):
    manager = MagnetPlaybackManager(
        cache_root=tmp_path / "cache", client=FakeWebTorrentClient()
    )
    started = manager.start(
        movie_id="movie-1",
        user_id="user-1",
        source_id="source-1",
        magnet="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
        torrent_url="",
    )

    status = wait_until_ready(manager, started["id"])
    assert status["state"] == "ready"
    assert status["file_name"] == "movie.mp4"
    stream = manager.open_range(started["id"], user_id="user-1", range_header="bytes=0-5")
    try:
        assert stream.handle.read(stream.length) == b"dragon"
        assert (stream.start, stream.end, stream.total) == (0, 5, 12)
    finally:
        stream.handle.close()

    session_root = tmp_path / "cache" / started["id"]
    manager.stop(started["id"], user_id="user-1")
    assert not session_root.exists()


def test_manager_rejects_media_path_outside_its_session(tmp_path):
    unsafe = tmp_path / "outside.mp4"
    manager = MagnetPlaybackManager(
        cache_root=tmp_path / "cache",
        client=FakeWebTorrentClient(unsafe_path=unsafe),
    )
    started = manager.start(
        movie_id="movie-1",
        user_id="user-1",
        source_id="source-1",
        magnet="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
        torrent_url="",
    )

    status = wait_until_ready(manager, started["id"])
    assert status["state"] == "failed"
    assert "unsafe media path" in status["message"]
