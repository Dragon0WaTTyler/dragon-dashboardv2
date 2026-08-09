import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flask import Flask

from app import create_app
from app.services.streaming import read_resource_token, rewrite_hls_manifest, transcode_stream


class HLSRewriteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test", "DATABASE": ":memory:"})

    def test_rewrites_segments_nested_manifests_and_keys(self):
        source = """#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="key.bin"
#EXT-X-STREAM-INF:BANDWIDTH=800000
low/index.m3u8
#EXTINF:6,
segment01.ts
"""
        with self.app.test_request_context("/my-tv/play/1"):
            output = rewrite_hls_manifest(source, "https://media.example/live/master.m3u8")
            proxy_lines = [line for line in output.splitlines() if line.startswith("/my-tv/resource/")]
            self.assertEqual(len(proxy_lines), 2)
            nested = read_resource_token(proxy_lines[0].rsplit("/", 1)[-1])
            segment = read_resource_token(proxy_lines[1].rsplit("/", 1)[-1])
            self.assertEqual(nested, "https://media.example/live/low/index.m3u8")
            self.assertEqual(segment, "https://media.example/live/segment01.ts")
            self.assertIn('/my-tv/resource/', output.splitlines()[1])

    def test_transcode_uses_audio_friendly_probe_and_output_settings(self):
        app = Flask(__name__)
        app.config.update(MYTV_FFMPEG="ffmpeg", MYTV_MAX_TRANSCODES=2)

        class _Stdout:
            def __init__(self):
                self.chunks = [b"video", b""]

            def read(self, _size):
                return self.chunks.pop(0)

        class _Process:
            def __init__(self):
                self.stdout = _Stdout()
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

        commands = []
        process = _Process()

        with (
            app.test_request_context("/"),
            patch("app.services.streaming.validate_stream_url", lambda url, allow_private=False: url),
            patch("app.services.streaming.shutil.which", lambda _name: "ffmpeg"),
            patch(
                "app.services.streaming.subprocess.Popen",
                lambda command, **_kwargs: commands.append(command) or process,
            ),
        ):
            response = transcode_stream("https://stream.example/video.mkv")
            self.assertEqual(b"".join(response.response), b"video")

        command = commands[0]
        self.assertIn("15000000", command)
        self.assertIn("50000000", command)
        self.assertIn("-ac", command)
        self.assertIn("2", command)
        self.assertIn("-ar", command)
        self.assertIn("48000", command)
        self.assertIn("-sn", command)
        self.assertIn("-dn", command)
        self.assertIn("-flush_packets", command)

    def test_transcode_can_start_from_a_specific_offset(self):
        app = Flask(__name__)
        app.config.update(MYTV_FFMPEG="ffmpeg", MYTV_MAX_TRANSCODES=2)

        class _Stdout:
            def __init__(self):
                self.chunks = [b"video", b""]

            def read(self, _size):
                return self.chunks.pop(0)

        class _Process:
            def __init__(self):
                self.stdout = _Stdout()
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

        commands = []
        process = _Process()

        with (
            app.test_request_context("/"),
            patch("app.services.streaming.validate_stream_url", lambda url, allow_private=False: url),
            patch("app.services.streaming.shutil.which", lambda _name: "ffmpeg"),
            patch(
                "app.services.streaming.subprocess.Popen",
                lambda command, **_kwargs: commands.append(command) or process,
            ),
        ):
            response = transcode_stream("https://stream.example/video.mkv", start_seconds=73.25)
            self.assertEqual(b"".join(response.response), b"video")

        command = commands[0]
        self.assertIn("-ss", command)
        self.assertIn("73.250", command)

    def test_transcode_rejects_an_empty_ffmpeg_output(self):
        app = Flask(__name__)
        app.config.update(MYTV_FFMPEG="ffmpeg", MYTV_MAX_TRANSCODES=2)

        class _Stdout:
            def read(self, _size):
                return b""

        class _Process:
            stdout = _Stdout()

            def poll(self):
                return 0

            def terminate(self):
                return None

            def wait(self, timeout=None):
                return 0

            def kill(self):
                return None

        with (
            app.test_request_context("/"),
            patch("app.services.streaming.validate_stream_url", lambda url, allow_private=False: url),
            patch("app.services.streaming.shutil.which", lambda _name: "ffmpeg"),
            patch("app.services.streaming.subprocess.Popen", lambda *_args, **_kwargs: _Process()),
        ):
            response = transcode_stream("https://stream.example/video.mkv")

        self.assertEqual(response.status_code, 503)
        self.assertIn(b"failed before video", response.get_data())

    def test_completed_local_file_bypasses_loopback_http(self):
        app = Flask(__name__)
        app.config.update(MYTV_FFMPEG="ffmpeg", MYTV_MAX_TRANSCODES=2)

        class _Stdout:
            def __init__(self):
                self.chunks = [b"video", b""]

            def read(self, _size):
                return self.chunks.pop(0)

        class _Process:
            stdout = _Stdout()
            stderr = None
            stopped = False

            def poll(self):
                return 0 if self.stopped else None

            def terminate(self):
                self.stopped = True

            def wait(self, timeout=None):
                self.stopped = True
                return 0

            def kill(self):
                self.stopped = True

        commands = []
        with TemporaryDirectory() as directory:
            source = Path(directory) / "episode.mp4"
            source.write_bytes(b"cached")
            with (
                app.test_request_context("/"),
                patch("app.services.streaming.shutil.which", lambda _name: "ffmpeg"),
                patch(
                    "app.services.streaming.subprocess.Popen",
                    lambda command, **_kwargs: commands.append(command) or _Process(),
                ),
            ):
                response = transcode_stream(source)
                self.assertEqual(b"".join(response.response), b"video")

        command = commands[0]
        self.assertIn(str(source.resolve()), command)
        self.assertNotIn("-reconnect", command)
        self.assertNotIn("-headers", command)


if __name__ == "__main__":
    unittest.main()
