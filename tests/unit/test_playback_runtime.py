from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

import pytest

from app.playback.runtime import MagnetPlaybackManager, PlaybackRuntimeError, _stream_kind

INFO_HASH = "0123456789abcdef0123456789abcdef01234567"
MAGNET = f"magnet:?xt=urn:btih:{INFO_HASH}"


class FakeWebTorrentClient:
    def __init__(self) -> None:
        self.results: dict[str, dict] = {}
        self.requests: list[tuple[str, dict]] = []

    def request(self, command: str, **payload: object) -> dict:
        self.requests.append((command, dict(payload)))
        session_id = str(payload["sessionId"])
        if command == "close":
            return {"closed": True}
        if command == "start":
            result = {
                "fileName": "movie.mp4",
                "totalBytes": 1000,
                "downloadedBytes": 250,
                "fileProgress": 0.25,
                "bufferPercent": 75,
                "streamUrl": "http://127.0.0.1:54321/dragon-stream/secret/hash/movie.mp4",
                "directStream": True,
                "complete": False,
                "peers": 2,
                "downloadSpeed": 1024,
                "timings": {"metadata_ms": 12, "stream_ready_ms": 18},
                "error": "",
            }
            self.results[session_id] = result
            return result
        return self.results[session_id]


def manager_for(tmp_path, *, cache_limit_gb=10, cache_ttl_hours=168):
    client = FakeWebTorrentClient()
    manager = MagnetPlaybackManager(
        cache_root=tmp_path / "cache",
        client=client,
        cache_limit_gb=cache_limit_gb,
        cache_ttl_hours=cache_ttl_hours,
    )
    return manager, client


def wait_until_ready(manager: MagnetPlaybackManager, session_id: str) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        status = manager.status(session_id, user_id="user-1")
        if status["state"] != "metadata":
            return status
        time.sleep(0.01)
    raise AssertionError("playback session did not finish preparing")


def test_manager_returns_direct_stream_metrics_and_preserves_cache(tmp_path):
    manager, client = manager_for(tmp_path)
    started = manager.start(
        movie_id="movie-1",
        user_id="user-1",
        source_id="source-1",
        magnet=MAGNET,
        origin="http://127.0.0.1:5050",
    )

    status = wait_until_ready(manager, started["id"])
    assert status["state"] == "ready"
    assert status["stream_url"].startswith("http://127.0.0.1:54321/dragon-stream/")
    assert status["file_progress"] == 0.25
    assert status["downloaded_bytes"] == 250
    assert status["buffer_percent"] == 75
    assert status["peers"] == 2
    assert status["startup_timings"]["metadata_ms"] == 12
    assert not any(command == "read" for command, _payload in client.requests)

    cache_file = manager.torrent_root / INFO_HASH / "movie.mp4"
    cache_file.write_bytes(b"cached-piece")
    manager.stop(started["id"], user_id="user-1")
    assert cache_file.exists()
    assert client.requests[-1][0] == "close"


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("movie.mp4", "direct"),
        ("episode.webm", "direct"),
        ("The.Sopranos.S01E01.1080p.BluRay.x265-RARBG.mp4", "transcode"),
        ("Boardwalk.Empire.S01E02.HEVC.10Bit.mp4", "transcode"),
        ("show.h.265.m4v", "transcode"),
        ("movie.mkv", "transcode"),
    ],
)
def test_stream_kind_transcodes_browser_hostile_direct_containers(file_name, expected):
    assert _stream_kind(file_name) == expected


def test_manager_enforces_session_ownership_and_loopback_origin(tmp_path):
    manager, _client = manager_for(tmp_path)
    started = manager.start(
        movie_id="movie-1",
        user_id="user-1",
        source_id="source-1",
        magnet=MAGNET,
        origin="http://localhost:5050",
    )
    with pytest.raises(PlaybackRuntimeError, match="not found"):
        manager.status(started["id"], user_id="user-2")
    with pytest.raises(PlaybackRuntimeError, match="loopback"):
        manager.start(
            movie_id="movie-1",
            user_id="user-1",
            source_id="source-1",
            magnet=MAGNET,
            origin="https://example.com",
        )


def test_cached_torrent_metadata_is_used_without_network(tmp_path):
    manager, client = manager_for(tmp_path)
    metadata = manager.metadata_root / f"{INFO_HASH}.torrent"
    metadata.write_bytes(b"d4:infode")
    started = manager.start(
        movie_id="movie-1",
        user_id="user-1",
        source_id="source-1",
        magnet=MAGNET,
        torrent_url="https://yts.bz/would-not-be-requested.torrent",
        origin="http://127.0.0.1:5050",
    )

    status = wait_until_ready(manager, started["id"])
    assert status["cache_hit"] is True
    start_payload = next(payload for command, payload in client.requests if command == "start")
    assert start_payload["torrentFile"] == str(metadata)


def test_cache_cleanup_expires_inactive_entries_but_keeps_active(tmp_path):
    manager, _client = manager_for(tmp_path, cache_ttl_hours=1)
    expired = manager.torrent_root / ("a" * 40)
    expired.mkdir(parents=True)
    (expired / "movie.mp4").write_bytes(b"old")
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(expired, (old, old))
    os.utime(expired / "movie.mp4", (old, old))

    started = manager.start(
        movie_id="movie-1",
        user_id="user-1",
        source_id="source-1",
        magnet=MAGNET,
        origin="http://127.0.0.1:5050",
    )
    active = manager.torrent_root / INFO_HASH
    active.mkdir(parents=True, exist_ok=True)
    (active / "piece").write_bytes(b"active")
    os.utime(active, (old, old))
    manager.cleanup_cache()

    assert not expired.exists()
    assert active.exists()
    manager.stop(started["id"], user_id="user-1")
