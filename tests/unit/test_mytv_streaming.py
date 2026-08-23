from __future__ import annotations

import threading

import pytest
from flask import Flask

from app.mytv import streaming


class _Stdout:
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks

    def read(self, _size: int) -> bytes:
        return self.chunks.pop(0)


class _Process:
    def __init__(self, chunks: list[bytes]):
        self.stdout = _Stdout(chunks)
        self.stopped = False

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self):
        self.stopped = True

    def wait(self, timeout=None):
        self.stopped = True
        return 0

    def kill(self):
        self.stopped = True


def _mock_transcoder(monkeypatch, chunks: list[bytes]):
    process = _Process(chunks)
    commands: list[list[str]] = []
    monkeypatch.setattr(streaming, "validate_stream_url", lambda url: url)
    monkeypatch.setattr(streaming.shutil, "which", lambda _name: "ffmpeg")
    monkeypatch.setattr(
        streaming.subprocess,
        "Popen",
        lambda command, **_kwargs: commands.append(command) or process,
    )
    monkeypatch.setattr(streaming, "_transcode_slots", threading.BoundedSemaphore(2))
    return process, commands


def test_transcode_waits_for_video_and_enables_reconnect(monkeypatch):
    process, commands = _mock_transcoder(
        monkeypatch, [b"ftypmoov", b"moofvideo-fragmentmdat", b""]
    )
    app = Flask(__name__)

    with app.test_request_context("/"):
        response = streaming.transcode_stream("https://stream.example/live.m3u8")
        assert b"".join(response.response) == b"ftypmoovmoofvideo-fragmentmdat"

    assert process.stopped is True
    assert "-reconnect" in commands[0]
    assert "-flush_packets" in commands[0]


def _mp4_box(box_type: bytes, payload: bytes) -> bytes:
    return (len(payload) + 8).to_bytes(4, "big") + box_type + payload


def _fragment(timestamp: int) -> bytes:
    tfhd = _mp4_box(b"tfhd", b"\x00\x00\x00\x00" + (1).to_bytes(4, "big"))
    tfdt = _mp4_box(b"tfdt", b"\x00\x00\x00\x00" + timestamp.to_bytes(4, "big"))
    moof = _mp4_box(b"moof", _mp4_box(b"traf", tfhd + tfdt))
    return moof + _mp4_box(b"mdat", b"media")


def test_fragment_deduplicator_skips_replayed_live_segment():
    deduplicator = streaming._FragmentDeduplicator()
    initial = _mp4_box(b"ftyp", b"isom") + _fragment(100)

    assert deduplicator.feed(initial) == initial
    assert deduplicator.feed(_fragment(95)) == b""
    assert deduplicator.feed(_fragment(105)) == _fragment(105)


def test_fragment_deduplicator_handles_chunks_split_inside_media_data():
    deduplicator = streaming._FragmentDeduplicator()
    fragment = _fragment(100)

    assert deduplicator.feed(fragment[:21]) == b""
    assert deduplicator.feed(fragment[21:]) == fragment


def test_transcode_rejects_an_offline_source_before_empty_200(monkeypatch):
    process, _commands = _mock_transcoder(monkeypatch, [b"ftypmoov", b""])
    app = Flask(__name__)

    with (
        app.test_request_context("/"),
        pytest.raises(streaming.StreamUnavailable, match="playable video"),
    ):
        streaming.transcode_stream("https://stream.example/offline.m3u8")

    assert process.stopped is True
    assert streaming._transcode_slots.acquire(blocking=False) is True
    assert streaming._transcode_slots.acquire(blocking=False) is True


def test_closing_unconsumed_transcode_response_releases_playback_slot(monkeypatch):
    process, _commands = _mock_transcoder(monkeypatch, [b"moofvideo-fragmentmdat"])
    app = Flask(__name__)

    with app.test_request_context("/"):
        response = streaming.transcode_stream("https://stream.example/live.m3u8")
        response.close()

    assert process.stopped is True
    assert streaming._transcode_slots.acquire(blocking=False) is True
    assert streaming._transcode_slots.acquire(blocking=False) is True
