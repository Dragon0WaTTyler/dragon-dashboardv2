import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.services.notion_media import NotionMediaClient, _decode_property, _encode_property
from app.services.releases import JackettProvider


PAGE_ID = "a" * 32


class FakeNotion:
    configured = True
    items = [
        {
            "notion_page_id": PAGE_ID,
            "title": "Existing Movie",
            "tmdb_id": 10,
            "media_type": "movie",
            "magnet_uri": "magnet:?xt=urn:btih:existing",
            "watched": False,
        }
    ]

    def __init__(self, _config):
        pass

    def list_media(self):
        return [dict(item) for item in self.items]

    def configuration(self):
        return {"configured": True, "missing_properties": []}

    def upsert(self, media):
        return {
            **media,
            "notion_page_id": PAGE_ID,
            "media_type": media["media_type"],
            "created": True,
        }

    def mark_watched(self, page_id, watched=True):
        return {**self.items[0], "notion_page_id": page_id, "watched": watched}


class FakeTmdb:
    configured = True

    def __init__(self, _config):
        pass

    def search(self, _query, _media_type="all"):
        return [
            {
                "title": "Missing Series",
                "tmdb_id": 20,
                "media_type": "tv",
                "year": 2026,
                "overview": "A series not present in Notion.",
                "poster_url": None,
            }
        ]

    def details(self, media_type, tmdb_id):
        return {
            "title": "Missing Series" if media_type == "tv" else "Missing Movie",
            "tmdb_id": tmdb_id,
            "media_type": media_type,
            "year": 2026,
            "overview": "Metadata from TMDB",
            "poster_url": "https://image.test/poster.jpg",
        }

    def seasons(self, _tmdb_id):
        return [{"season_number": 1, "name": "Season 1", "episode_count": 2}]

    def episodes(self, _tmdb_id, season_number):
        return [{"episode_number": 1, "season_number": season_number, "name": "Pilot"}]

    def release_query(self, media_type, tmdb_id, season=None, episode=None):
        return self.details(media_type, tmdb_id), f"Missing Series S{season:02d}E{episode:02d}"


class FakeProvider:
    configured = True

    def search(self, _query, _media_type="all"):
        return [
            {
                "title": "Release S01E01",
                "magnet_uri": "magnet:?xt=urn:btih:new",
                "seeders": 12,
                "size": 1000,
                "tracker": "Test",
            }
        ]


class MediaApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE": str(Path(self.tempdir.name) / "test.sqlite3"),
                "NOTION_TOKEN": "secret",
                "NOTION_DATABASE_ID": "1" * 32,
                "TMDB_API_TOKEN": "token",
                "JACKETT_API_KEY": "key",
            }
        )
        self.client = self.app.test_client()
        self.client.get("/media")
        with self.client.session_transaction() as flask_session:
            self.csrf = flask_session["csrf_token"]

    def tearDown(self):
        self.tempdir.cleanup()

    def write(self, url, payload):
        return self.client.post(
            url,
            json=payload,
            headers={"X-CSRF-Token": self.csrf},
        )

    @patch("app.media.build_release_provider", return_value=FakeProvider())
    @patch("app.media.TmdbClient", FakeTmdb)
    @patch("app.media.NotionMediaClient", FakeNotion)
    def test_bootstrap_is_notion_backed(self, _provider):
        response = self.client.get("/media/api/bootstrap")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual([item["title"] for item in data["library"]], ["Existing Movie"])
        self.assertTrue(data["library"][0]["playback"]["magnet_uri"].startswith("magnet:?"))

    @patch("app.media.TmdbClient", FakeTmdb)
    @patch("app.media.NotionMediaClient", FakeNotion)
    def test_search_returns_missing_tmdb_result_after_notion_check(self):
        data = self.client.get("/media/api/search?q=missing&type=all").get_json()
        self.assertEqual(data["library"], [])
        self.assertEqual(data["discovery"][0]["title"], "Missing Series")
        self.assertFalse(data["discovery"][0]["in_library"])

    @patch("app.media.build_release_provider", return_value=FakeProvider())
    @patch("app.media.TmdbClient", FakeTmdb)
    def test_episode_release_search(self, _provider):
        data = self.client.get(
            "/media/api/releases?type=tv&tmdb_id=20&season=1&episode=1"
        ).get_json()
        self.assertEqual(data["release_query"], "Missing Series S01E01")
        self.assertEqual(data["results"][0]["seeders"], 12)

    @patch("app.media.TmdbClient", FakeTmdb)
    @patch("app.media.NotionMediaClient", FakeNotion)
    def test_add_series_requires_episode_then_writes_notion(self):
        invalid = self.write(
            "/media/api/library",
            {
                "media_type": "tv",
                "tmdb_id": 20,
                "magnet_uri": "magnet:?xt=urn:btih:new",
            },
        )
        self.assertEqual(invalid.status_code, 400)

        valid = self.write(
            "/media/api/library",
            {
                "media_type": "tv",
                "tmdb_id": 20,
                "season": 1,
                "episode": 1,
                "release_title": "Release S01E01",
                "magnet_uri": "magnet:?xt=urn:btih:new",
            },
        )
        self.assertEqual(valid.status_code, 201)
        item = valid.get_json()["item"]
        self.assertEqual(item["title"], "Missing Series")
        self.assertEqual(item["season"], 1)
        self.assertEqual(item["playback"]["mode"], "webtorrent")

    def test_media_write_requires_csrf(self):
        response = self.client.post("/media/api/library", json={})
        self.assertEqual(response.status_code, 403)


class MediaServiceTests(unittest.TestCase):
    def test_notion_property_codec_supports_existing_schema_types(self):
        encoded = _encode_property("rich_text", "magnet:?xt=urn:btih:test")
        self.assertEqual(encoded["rich_text"][0]["text"]["content"], "magnet:?xt=urn:btih:test")
        decoded = _decode_property(
            {"type": "select", "select": {"name": "Series"}}
        )
        self.assertEqual(decoded, "Series")

    def test_notion_rows_without_type_remain_backward_compatible_movies(self):
        app = create_app({"TESTING": True, "DATABASE": ":memory:"})
        client = NotionMediaClient(app.config)
        client._schema_cache = {
            "Name": {"type": "title"},
            "TMDB ID": {"type": "number"},
        }
        item = client._page_to_media(
            {
                "id": PAGE_ID,
                "properties": {
                    "Name": {"type": "title", "title": [{"plain_text": "Old Movie"}]},
                    "TMDB ID": {"type": "number", "number": 42},
                },
            }
        )
        self.assertEqual(item["media_type"], "movie")
        self.assertEqual(item["tmdb_id"], 42)

    def test_jackett_filters_seeders_missing_magnets_and_duplicates(self):
        app = create_app(
            {
                "TESTING": True,
                "DATABASE": ":memory:",
                "JACKETT_API_KEY": "key",
                "JACKETT_MIN_SEEDERS": 5,
                "JACKETT_RESULT_LIMIT": 10,
            }
        )
        provider = JackettProvider(app.config)
        parsed = provider._parse_json(
            {
                "Results": [
                    {"Title": "Good", "MagnetUri": "magnet:?xt=urn:btih:one&dn=a", "Seeders": 9, "Size": 50, "Tracker": "A"},
                    {"Title": "Duplicate stronger", "MagnetUri": "magnet:?xt=urn:btih:one&dn=b", "Seeders": 12, "Size": 50, "Tracker": "B"},
                    {"Title": "Too few", "MagnetUri": "magnet:?xt=urn:btih:two", "Seeders": 4},
                    {"Title": "No magnet", "Seeders": 100},
                ]
            }
        )
        results = provider._filter(parsed)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Duplicate stronger")


if __name__ == "__main__":
    unittest.main()
