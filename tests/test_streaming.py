import unittest

from app import create_app
from app.services.streaming import read_resource_token, rewrite_hls_manifest


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


if __name__ == "__main__":
    unittest.main()

