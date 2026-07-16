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
    process, commands = _mock_transcoder(monkeypatch, [b"first", b"second", b""])
    app = Flask(__name__)

    with app.test_request_context("/"):
        response = streaming.transcode_stream("https://stream.example/live.m3u8")
        assert b"".join(response.response) == b"firstsecond"

    assert process.stopped is True
    assert "-reconnect" in commands[0]
    assert "-flush_packets" in commands[0]


def test_transcode_rejects_an_offline_source_before_empty_200(monkeypatch):
    process, _commands = _mock_transcoder(monkeypatch, [b""])
    app = Flask(__name__)

    with (
        app.test_request_context("/"),
        pytest.raises(streaming.StreamUnavailable, match="offline"),
    ):
        streaming.transcode_stream("https://stream.example/offline.m3u8")

    assert process.stopped is True
    assert streaming._transcode_slots.acquire(blocking=False) is True
    assert streaming._transcode_slots.acquire(blocking=False) is True
