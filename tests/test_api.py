import tempfile
import unittest
from pathlib import Path

from app import create_app
from app.db import connect_db


class MyTVApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = str(Path(self.tempdir.name) / "test.sqlite3")
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE": self.database,
                "MYTV_ALLOW_PRIVATE_STREAMS": True,
            }
        )
        self.client = self.app.test_client()
        self._seed()
        self.client.get("/my-tv")
        with self.client.session_transaction() as flask_session:
            self.csrf = flask_session["csrf_token"]

    def tearDown(self):
        self.tempdir.cleanup()

    def _seed(self):
        db = connect_db(self.database)
        db.execute(
            """
            INSERT INTO playlists(id, name, github_path, source_url, imported, available, enabled, channel_count, group_count, sync_status)
            VALUES (1, 'Package', 'one.m3u', 'https://example.test/one.m3u', 1, 1, 1, 2, 1, 'ready')
            """
        )
        db.execute(
            "INSERT INTO channel_groups(id, playlist_id, name, enabled, channel_count) VALUES (1, 1, 'News', 1, 2)"
        )
        db.executemany(
            """
            INSERT INTO channels(id, playlist_id, group_id, external_key, name, stream_url, stream_kind, enabled_override, position, last_seen_sync)
            VALUES (?, 1, 1, ?, ?, ?, ?, ?, ?, 'seed')
            """,
            [
                (1, "one", "News One", "https://stream.example/one.m3u8", "hls", None, 1),
                (2, "two", "News Two", "https://stream.example/two.ts", "transport", 0, 2),
            ],
        )
        db.commit()
        db.close()

    def write(self, method, url, payload):
        return self.client.open(
            url,
            method=method,
            json=payload,
            headers={"X-CSRF-Token": self.csrf},
        )

    def test_bootstrap_and_enabled_channel_filter(self):
        bootstrap = self.client.get("/my-tv/api/bootstrap").get_json()
        self.assertEqual(bootstrap["stats"]["total_channels"], 2)
        self.assertEqual(bootstrap["stats"]["enabled_channels"], 1)
        channels = self.client.get("/my-tv/api/channels?state=enabled").get_json()
        self.assertEqual([item["name"] for item in channels["channels"]], ["News One"])

    def test_group_off_allows_explicit_channel_exception(self):
        response = self.write("PATCH", "/my-tv/api/groups/1", {"enabled": False})
        self.assertEqual(response.status_code, 200)
        enabled = self.client.get("/my-tv/api/channels?state=enabled").get_json()
        self.assertEqual(enabled["pagination"]["total"], 0)

        response = self.write("PATCH", "/my-tv/api/channels/2", {"enabled": True})
        self.assertEqual(response.status_code, 200)
        enabled = self.client.get("/my-tv/api/channels?state=enabled").get_json()
        self.assertEqual([item["name"] for item in enabled["channels"]], ["News Two"])

    def test_source_master_switch_blocks_channel_override(self):
        self.write("PATCH", "/my-tv/api/channels/2", {"enabled": True})
        self.write("PATCH", "/my-tv/api/playlists/1", {"enabled": False})
        enabled = self.client.get("/my-tv/api/channels?state=enabled").get_json()
        self.assertEqual(enabled["pagination"]["total"], 0)
        playback = self.client.get("/my-tv/api/channels/2/playback")
        self.assertEqual(playback.status_code, 404)

    def test_bulk_inherit_clears_channel_overrides(self):
        response = self.write("POST", "/my-tv/api/groups/1/channels", {"action": "inherit"})
        self.assertEqual(response.status_code, 200)
        all_channels = self.client.get("/my-tv/api/channels?state=all").get_json()
        self.assertTrue(all(item["enabled_override"] is None for item in all_channels["channels"]))

    def test_api_write_requires_csrf(self):
        response = self.client.patch("/my-tv/api/playlists/1", json={"enabled": False})
        self.assertEqual(response.status_code, 403)

    def test_playback_does_not_expose_upstream_url(self):
        response = self.client.get("/my-tv/api/channels/1/playback")
        data = response.get_json()
        self.assertEqual(data["url"], "/my-tv/play/1")
        self.assertNotIn("stream.example", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()

