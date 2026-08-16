from datetime import timedelta
from io import BytesIO

from werkzeug.datastructures import MultiDict

from app.extensions import db
from app.mytv.models import TVChannel, TVSource, TVTheme
from app.mytv.source_manager import TVSourceManager
from app.reading.models import Article, ReadingSource
from app.reading.services import ReadingService
from app.shared.time import utc_now
from tests.conftest import csrf_from

M3U = b"""#EXTM3U
#EXTINF:-1 tvg-id="news.one" group-title="News",News One
https://stream.example/news-one.m3u8
#EXTINF:-1 tvg-id="sport.one" group-title="Sports",Sport One
https://stream.example/sport-one.m3u8
"""


class FeedClient:
    @staticmethod
    def fetch(url):
        assert url == "https://feeds.example.test/news.xml"
        return {
            "entries": [
                {
                    "external_id": "story-one",
                    "title": "Managed RSS story",
                    "url": "https://news.example.test/story-one",
                    "excerpt": "Stored by the source manager.",
                    "image_url": "https://images.example.test/story-one.jpg",
                }
            ]
        }


class TVSourceResponse:
    status_code = 200
    headers = {"Content-Length": str(len(M3U)), "ETag": '"draft-etag"'}

    def __init__(self, payload=None):
        self.payload = payload

    def json(self):
        return self.payload

    @staticmethod
    def iter_content(chunk_size):
        assert chunk_size == 262_144
        yield M3U

    @staticmethod
    def close():
        return None


class TVSourceSession:
    def get(self, url, **kwargs):
        if "api.github.com" in url:
            return TVSourceResponse(
                {
                    "tree": [
                        {"type": "blob", "path": "lists/morocco.m3u", "sha": "abc", "size": 12},
                        {"type": "blob", "path": "README.md", "sha": "def", "size": 4},
                    ]
                }
            )
        return TVSourceResponse()


def test_tv_draft_supports_url_github_repository_and_github_file(app):
    app.config["MYTV_ALLOW_PRIVATE_STREAMS"] = True
    manager = TVSourceManager(session=TVSourceSession())
    common = {
        "name": "Draft source",
        "refresh_interval_minutes": "60",
        "enabled": "on",
    }
    with app.app_context():
        direct = manager.test_configuration(
            MultiDict(common | {"source_type": "m3u_url", "locator": "https://tv.test/list.m3u"}),
            None,
        )
        repository = manager.test_configuration(
            MultiDict(
                common
                | {
                    "source_type": "github_repository",
                    "locator": "dragon/tv-lists",
                    "branch": "main",
                    "file_pattern": "lists/*.m3u",
                }
            ),
            None,
        )
        github_file = manager.test_configuration(
            MultiDict(
                common
                | {
                    "source_type": "github_file",
                    "locator": "https://github.com/dragon/tv-lists/blob/main/morocco.m3u",
                }
            ),
            None,
        )
    assert direct == {"files": 1}
    assert repository == {"files": 1}
    assert github_file == {"files": 1}


def test_draft_sources_can_be_tested_without_being_saved(authenticated_client, app):
    app.config["MYTV_ALLOW_PRIVATE_STREAMS"] = True
    app.extensions["dragon_feed_client"] = FeedClient()

    tv_page = authenticated_client.get("/admin/sections/mytv")
    token = csrf_from(tv_page)
    with app.app_context():
        initial_tv_sources = db.session.query(TVSource).count()
    tv_response = authenticated_client.post(
        "/admin/sections/mytv/sources/test-draft",
        data={
            "csrf_token": token,
            "name": "Unsaved local source",
            "source_type": "local_file",
            "refresh_interval_minutes": "60",
            "enabled": "on",
            "local_file": (BytesIO(M3U), "draft.m3u"),
        },
        content_type="multipart/form-data",
        headers={"Accept": "application/json"},
    )
    assert tv_response.status_code == 200
    assert tv_response.json == {"ok": True, "message": "Connection healthy: 1 M3U file(s) found."}

    news_page = authenticated_client.get("/admin/sections/reading")
    news_response = authenticated_client.post(
        "/admin/sections/reading/sources/test-draft",
        data={
            "csrf_token": csrf_from(news_page),
            "name": "Unsaved feed",
            "feed_url": "https://feeds.example.test/news.xml",
            "language": "en",
            "refresh_interval_minutes": "60",
            "maximum_articles": "50",
            "active": "on",
        },
        headers={"Accept": "application/json"},
    )
    assert news_response.status_code == 200
    assert news_response.json == {"ok": True, "message": "Connection healthy: 1 entries found."}
    with app.app_context():
        assert db.session.query(TVSource).count() == initial_tv_sources
        assert db.session.query(ReadingSource).count() == 0


def test_news_retention_can_protect_or_remove_saved_articles(app):
    old = utc_now() - timedelta(days=100)
    with app.app_context():
        unread = Article(title="Old unread", url="https://example.test/unread", created_at=old)
        saved = Article(
            title="Old saved", url="https://example.test/saved", status="saved", created_at=old
        )
        db.session.add_all([unread, saved])
        db.session.commit()
        saved_id = saved.id

        assert ReadingService.trim_by_age(days=30, protect_saved=True) == 1
        db.session.commit()
        assert db.session.get(Article, saved_id) is not None

        assert ReadingService.trim_by_age(days=30, protect_saved=False) == 1
        db.session.commit()
        assert db.session.get(Article, saved_id) is None


def test_local_m3u_source_can_be_added_refreshed_managed_and_deleted(authenticated_client, app):
    app.config["MYTV_ALLOW_PRIVATE_STREAMS"] = True
    page = authenticated_client.get("/admin/sections/mytv")
    token = csrf_from(page)
    created = authenticated_client.post(
        "/admin/sections/mytv/sources",
        data={
            "csrf_token": token,
            "name": "Local test channels",
            "source_type": "local_file",
            "locator": "",
            "branch": "main",
            "file_pattern": "*.m3u",
            "refresh_interval_minutes": "60",
            "enabled": "on",
            "auto_refresh": "on",
            "local_file": (BytesIO(M3U), "local-test.m3u"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert created.status_code == 200
    assert "TV source saved" in created.get_data(as_text=True)
    assert "Local test channels" in created.get_data(as_text=True)

    with app.app_context():
        source = db.session.scalar(
            db.select(TVSource).where(TVSource.name == "Local test channels")
        )
        source_id = source.id

    refreshed = authenticated_client.post(
        f"/admin/sections/mytv/sources/{source_id}/refresh",
        data={"csrf_token": token},
        follow_redirects=True,
    )
    html = refreshed.get_data(as_text=True)
    assert refreshed.status_code == 200
    assert "2 channels from 1 file" in html
    assert "News" in html
    assert "Sports" in html

    with app.app_context():
        assert db.session.query(TVChannel).count() == 2
        categories = list(db.session.scalars(db.select(TVTheme).order_by(TVTheme.name)))
        assert [item.name for item in categories] == ["News", "Sports"]
        assert all(item.enabled for item in categories)
        news_id = categories[0].id
        sport_id = categories[1].id

    category = authenticated_client.post(
        f"/admin/sections/mytv/categories/{news_id}",
        data={"csrf_token": token, "name": "World News", "enabled": "on"},
        follow_redirects=True,
    )
    assert "TV category updated" in category.get_data(as_text=True)
    merged = authenticated_client.post(
        f"/admin/sections/mytv/categories/{sport_id}/merge",
        data={"csrf_token": token, "target_id": str(news_id)},
        follow_redirects=True,
    )
    assert "TV categories merged" in merged.get_data(as_text=True)

    paused = authenticated_client.post(
        f"/admin/sections/mytv/sources/{source_id}/toggle",
        data={"csrf_token": token},
        follow_redirects=True,
    )
    assert "TV source paused" in paused.get_data(as_text=True)

    deleted = authenticated_client.post(
        f"/admin/sections/mytv/sources/{source_id}/delete",
        data={"csrf_token": token, "confirmed": "yes", "data_action": "delete"},
        follow_redirects=True,
    )
    assert "TV source removed" in deleted.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(TVSource, source_id) is None
        assert db.session.query(TVChannel).count() == 0


def test_save_and_import_loads_custom_m3u_immediately(authenticated_client, app):
    page = authenticated_client.get("/admin/sections/mytv")
    response = authenticated_client.post(
        "/admin/sections/mytv/sources",
        data={
            "csrf_token": csrf_from(page),
            "name": "Immediate custom source",
            "source_type": "local_file",
            "refresh_interval_minutes": "60",
            "enabled": "on",
            "auto_refresh": "on",
            "submit_action": "import",
            "local_file": (BytesIO(M3U), "immediate.m3u"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "saved and imported: 2 channels from 1 file" in response.get_data(as_text=True)
    with app.app_context():
        source = db.session.scalar(
            db.select(TVSource).where(TVSource.name == "Immediate custom source")
        )
        assert source.last_success_at is not None
        assert len(source.playlists) == 1
        assert source.playlists[0].channel_count == 2


def test_rss_source_can_be_tested_refreshed_edited_paused_and_removed(authenticated_client, app):
    app.config["MYTV_ALLOW_PRIVATE_STREAMS"] = True
    app.extensions["dragon_feed_client"] = FeedClient()
    page = authenticated_client.get("/admin/sections/reading")
    token = csrf_from(page)
    created = authenticated_client.post(
        "/admin/sections/reading/sources",
        data={
            "csrf_token": token,
            "name": "Managed feed",
            "feed_url": "https://feeds.example.test/news.xml",
            "category": "Technology",
            "language": "en",
            "refresh_interval_minutes": "60",
            "maximum_articles": "50",
            "active": "on",
            "auto_refresh": "on",
            "download_images": "on",
            "submit_action": "test",
        },
        follow_redirects=True,
    )
    assert created.status_code == 200
    assert "RSS source added and tested: 1 entries found" in created.get_data(as_text=True)

    with app.app_context():
        source = db.session.scalar(
            db.select(ReadingSource).where(ReadingSource.name == "Managed feed")
        )
        source_id = source.id
        assert source.health_state == "healthy"

    refreshed = authenticated_client.post(
        f"/admin/sections/reading/sources/{source_id}/refresh",
        data={"csrf_token": token},
        follow_redirects=True,
    )
    assert "RSS refreshed: 1 new and 0 updated" in refreshed.get_data(as_text=True)
    with app.app_context():
        article = db.session.scalar(db.select(Article).where(Article.title == "Managed RSS story"))
        assert article is not None
        assert article.image_url == "https://images.example.test/story-one.jpg"
        article_id = article.id

    category = authenticated_client.post(
        "/admin/sections/reading/categories",
        data={
            "csrf_token": token,
            "current": "Technology",
            "name": "Tech",
            "active": "on",
        },
        follow_redirects=True,
    )
    assert "News category updated" in category.get_data(as_text=True)

    paused = authenticated_client.post(
        f"/admin/sections/reading/sources/{source_id}/toggle",
        data={"csrf_token": token},
        follow_redirects=True,
    )
    assert "RSS source paused" in paused.get_data(as_text=True)

    deleted = authenticated_client.post(
        f"/admin/sections/reading/sources/{source_id}/delete",
        data={"csrf_token": token, "confirmed": "yes", "data_action": "keep"},
        follow_redirects=True,
    )
    assert "RSS source removed" in deleted.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(ReadingSource, source_id) is None
        kept = db.session.get(Article, article_id)
        assert kept is not None
        assert kept.source_id is None


def test_source_delete_requires_explicit_confirmation(authenticated_client, app):
    with app.app_context():
        source = ReadingSource(name="Protected feed", feed_url="https://example.test/feed")
        db.session.add(source)
        db.session.commit()
        source_id = source.id
    page = authenticated_client.get("/admin/sections/reading")
    response = authenticated_client.post(
        f"/admin/sections/reading/sources/{source_id}/delete",
        data={"csrf_token": csrf_from(page), "data_action": "delete"},
        follow_redirects=True,
    )
    assert "Confirm exactly what should happen" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(ReadingSource, source_id) is not None
