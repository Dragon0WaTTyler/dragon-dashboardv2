import unittest

from app.services.m3u import ChannelEntry, classify_stream, parse_m3u


class M3UParserTests(unittest.TestCase):
    def test_parses_channel_metadata_and_stream_kind(self):
        content = [
            "\ufeff#EXTM3U",
            '#EXTINF:-1 tvg-id="news.ma" tvg-name="News HD" tvg-logo="https://img.example/logo.png" group-title="Morocco",News HD',
            "https://stream.example/live/index.m3u8",
        ]
        channels = list(parse_m3u(content))
        self.assertEqual(len(channels), 1)
        channel = channels[0]
        self.assertEqual(channel.name, "News HD")
        self.assertEqual(channel.group, "Morocco")
        self.assertEqual(channel.tvg_id, "news.ma")
        self.assertEqual(channel.kind, "hls")

    def test_ignores_unpaired_and_unsupported_lines(self):
        content = [
            "https://orphan.example/stream.ts",
            "# A comment",
            '#EXTINF:-1 group-title="Sports",Sports One',
            "udp://239.0.0.1:1234",
        ]
        self.assertEqual(list(parse_m3u(content)), [])

    def test_external_key_survives_expiring_url_changes(self):
        first = ChannelEntry("Channel", "Group", "https://a.example/live/token-one/1.ts")
        second = ChannelEntry("Channel", "Group", "https://b.example/live/token-two/1.ts")
        self.assertEqual(first.external_key, second.external_key)

    def test_classifies_common_formats(self):
        self.assertEqual(classify_stream("https://a.test/live.m3u8?token=x"), "hls")
        self.assertEqual(classify_stream("https://a.test/movie.mp4"), "file")
        self.assertEqual(classify_stream("https://a.test/live/1.ts"), "transport")
        self.assertEqual(classify_stream("https://a.test/live/1"), "stream")


if __name__ == "__main__":
    unittest.main()

