import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from flask import Flask

from app import create_app
from app.services.streaming import (
    _open_upstream,
    read_resource_token,
    rewrite_hls_manifest,
    transcode_stream,
)


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
        with self.app.test_request_context("/iptv/play/1"):
            output = rewrite_hls_manifest(source, "https://media.example/live/master.m3u8")
            proxy_lines = [line for line in output.splitlines() if line.startswith("/iptv/resource/")]
            self.assertEqual(len(proxy_lines), 2)
            nested = read_resource_token(proxy_lines[0].rsplit("/", 1)[-1])
            segment = read_resource_token(proxy_lines[1].rsplit("/", 1)[-1])
            self.assertEqual(nested, "https://media.example/live/low/index.m3u8")
            self.assertEqual(segment, "https://media.example/live/segment01.ts")
            self.assertIn('/iptv/resource/', output.splitlines()[1])

    def test_rewrite_preserves_live_sequence_and_all_segments(self):
        segments = "".join(f"#EXTINF:6,\nsegment{index}.ts\n" for index in range(16))
        source = f"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:100\n{segments}"

        with self.app.test_request_context("/iptv/play/1"):
            output = rewrite_hls_manifest(source, "https://media.example/live/index.m3u8")
            first_segment = read_resource_token(
                next(
                    line for line in output.splitlines() if line.startswith("/iptv/resource/")
                ).rsplit("/", 1)[-1]
            )

        lines = output.splitlines()
        self.assertEqual(lines[1], "#EXT-X-MEDIA-SEQUENCE:100")
        segment_count = sum(line.startswith("#EXTINF:") for line in lines)
        self.assertEqual(segment_count, 16)
        self.assertEqual(first_segment, "https://media.example/live/segment0.ts")

    def test_rewrite_preserves_byte_range_playlists(self):
        segments = "".join(
            f"#EXTINF:6,\n#EXT-X-BYTERANGE:1000\nsegment{index}.m4s\n"
            for index in range(16)
        )
        source = f"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:100\n{segments}"

        with self.app.test_request_context("/iptv/play/1"):
            output = rewrite_hls_manifest(source, "https://media.example/live/index.m3u8")

        lines = output.splitlines()
        self.assertEqual(lines[1], "#EXT-X-MEDIA-SEQUENCE:100")
        self.assertEqual(sum(line.startswith("#EXTINF:") for line in lines), 16)

    def test_rewrite_preserves_encryption_state_without_reordering(self):
        old_segments = "".join(f"#EXTINF:6,\nold{index}.ts\n" for index in range(2))
        new_segments = "".join(f"#EXTINF:6,\nnew{index}.ts\n" for index in range(14))
        source = (
            "#EXTM3U\n"
            "#EXT-X-MEDIA-SEQUENCE:100\n"
            '#EXT-X-KEY:METHOD=AES-128,URI="old.key"\n'
            f"{old_segments}"
            '#EXT-X-KEY:METHOD=AES-128,URI="new.key"\n'
            f"{new_segments}"
        )

        with self.app.test_request_context("/iptv/play/1"):
            output = rewrite_hls_manifest(source, "https://media.example/live/index.m3u8")
            lines = output.splitlines()
            first_segment = next(index for index, line in enumerate(lines) if line.startswith("#EXTINF:"))
            key_line = [line for line in lines[:first_segment] if line.startswith("#EXT-X-KEY:")][0]
            key_token = re.search(r'URI="(/iptv/resource/[^"]+)"', key_line)
            self.assertIsNotNone(key_token)
            self.assertEqual(
                read_resource_token(key_token.group(1).rsplit("/", 1)[-1]),
                "https://media.example/live/old.key",
            )

    def test_hls_proxy_retries_transient_upstream_failures(self):
        first = Mock(status_code=503, headers={})
        second = Mock(status_code=200, headers={})
        with (
            self.app.test_request_context("/iptv/resource/token"),
            patch("app.services.streaming.requests.get", side_effect=[first, second]) as get,
            patch("app.services.streaming.time.sleep"),
            patch("app.services.streaming.validate_stream_url", return_value="https://media.example/live.m3u8"),
        ):
            response, final_url = _open_upstream("https://media.example/live.m3u8")

        self.assertIs(response, second)
        self.assertEqual(final_url, "https://media.example/live.m3u8")
        self.assertEqual(get.call_count, 2)
        first.close.assert_called_once()

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
