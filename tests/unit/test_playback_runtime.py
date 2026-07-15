from __future__ import annotations

import base64
import time

import pytest

from app.playback.runtime import MagnetPlaybackManager, PlaybackRuntimeError


class FakeWebTorrentClient:
    def __init__(self, *, invalid_data: bool = False) -> None:
        self.invalid_data = invalid_data
        self.results: dict[str, dict] = {}

    def request(self, command: str, **payload: object) -> dict:
        session_id = str(payload["sessionId"])
        if command == "close":
            return {"closed": True}
        if command == "start":
            result = {
                "fileName": "movie.mp4",
                "totalBytes": len(b"dragon-video"),
                "directStream": True,
                "complete": False,
                "peers": 2,
                "downloadSpeed": 1024,
                "error": "",
            }
            self.results[session_id] = result
            return result
        if command == "read":
            if self.invalid_data:
                return {"data": "not-base64", "bytes": 0}
            start = int(payload["start"])
            end = int(payload["end"])
            data = b"dragon-video"[start : end + 1]
            return {"data": base64.b64encode(data).decode(), "bytes": len(data)}
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
    payload = manager.read_chunk(
        started["id"], user_id="user-1", start=stream.start, end=stream.end
    )
    assert payload == b"dragon"
    assert (stream.start, stream.end, stream.total) == (0, 5, 12)

    session_root = tmp_path / "cache" / started["id"]
    manager.stop(started["id"], user_id="user-1")
    assert not session_root.exists()


def test_manager_rejects_invalid_runtime_stream_data(tmp_path):
    manager = MagnetPlaybackManager(
        cache_root=tmp_path / "cache",
        client=FakeWebTorrentClient(invalid_data=True),
    )
    started = manager.start(
        movie_id="movie-1",
        user_id="user-1",
        source_id="source-1",
        magnet="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
        torrent_url="",
    )

    wait_until_ready(manager, started["id"])
    with pytest.raises(PlaybackRuntimeError, match="invalid stream data"):
        manager.read_chunk(started["id"], user_id="user-1", start=0, end=5)
