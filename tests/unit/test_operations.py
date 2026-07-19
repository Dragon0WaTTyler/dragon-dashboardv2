from datetime import timedelta

from app.extensions import db
from app.reading.models import Article, ReadingSource
from app.shared.auto_sync import _pockettube_sync_due, _reading_sync_due
from app.shared.models import Operation
from app.shared.models import SnapshotRecord
from app.shared.operations import OperationService
from app.shared.refresh import OperationCoordinator
from app.shared.time import utc_now
from app.youtube.models import YouTubeVideo


def test_operation_service_records_safe_success(app):
    with app.app_context():
        operation = OperationService.start(kind="refresh", domain="reading")
        OperationService.complete(operation, counts={"created": 3})
        saved = OperationService.get(operation.id)

        assert saved is not None
        assert saved.status == "completed"
        assert saved.counts == {"created": 3}
        assert saved.completed_at is not None


def test_operation_service_redacts_failure_details(app):
    with app.app_context():
        operation = OperationService.start(kind="sync", domain="youtube")
        OperationService.fail(
            operation,
            r"Proxy failed at C:\private\oauth.json token=do-not-leak",
        )
        saved = db.session.get(Operation, operation.id)

        assert saved.status == "failed"
        assert "do-not-leak" not in saved.safe_error
        assert "C:\\private" not in saved.safe_error
        assert "[redacted]" in saved.safe_error


def test_youtube_operation_uses_explicit_injected_playlist_client(app):
    class Client:
        def fetch_playlist(self, playlist_id, *, maximum):
            assert playlist_id == "PL-test-playlist-123"
            return [
                {
                    "id": "item-1",
                    "snippet": {
                        "title": "One video",
                        "resourceId": {"videoId": "video-1"},
                    },
                }
            ]

    with app.app_context():
        app.config["DRAGON_YOUTUBE_SYNC_ENABLED"] = True
        app.config["DRAGON_YOUTUBE_WATCH_LATER_PLAYLIST_ID"] = "PL-test-playlist-123"
        app.extensions["dragon_youtube_playlist_client"] = Client()

        operation = OperationCoordinator.run(kind="sync", domain="youtube_watch_later")

        assert operation.status == "completed"
        assert operation.counts["videos"] == 1
        assert db.session.scalar(db.select(YouTubeVideo)).source == "watch_later"


def test_pockettube_auto_sync_waits_two_hours_between_runs(app):
    with app.app_context():
        db.session.add(
            SnapshotRecord(
                domain="youtube_pockettube",
                schema_version="test",
                relative_path="file://test.json",
                checksum="fresh",
                generated_at=utc_now(),
                last_success_at=utc_now(),
            )
        )
        db.session.commit()

        assert _pockettube_sync_due() is False

        snapshot = db.session.scalar(
            db.select(SnapshotRecord).where(
                SnapshotRecord.domain == "youtube_pockettube"
            )
        )
        snapshot.last_success_at = utc_now() - timedelta(hours=2, minutes=1)
        db.session.commit()

        assert _pockettube_sync_due() is True


def test_reading_auto_sync_waits_five_minutes_between_runs(app):
    with app.app_context():
        db.session.add(
            SnapshotRecord(
                domain="reading",
                schema_version="test",
                relative_path="database://articles",
                checksum="fresh",
                generated_at=utc_now(),
                last_success_at=utc_now(),
            )
        )
        db.session.commit()

        assert _reading_sync_due() is False

        snapshot = db.session.scalar(
            db.select(SnapshotRecord).where(SnapshotRecord.domain == "reading")
        )
        snapshot.last_success_at = utc_now() - timedelta(minutes=6)
        db.session.commit()

        assert _reading_sync_due() is True


def test_reading_operation_syncs_active_sources_with_injected_client(app):
    class Client:
        @staticmethod
        def fetch(url):
            assert url == "https://example.test/feed.xml"
            return {
                "entries": [
                    {
                        "external_id": "fresh-article",
                        "title": "Fresh from the feed",
                        "url": "https://example.test/fresh",
                        "author": "Desk",
                        "topic": "News",
                        "excerpt": "A current feed summary.",
                        "image_url": "https://images.example.test/fresh.jpg",
                        "published_at": None,
                    }
                ]
            }

    with app.app_context():
        source = ReadingSource(
            name="Example Journal",
            feed_url="https://example.test/feed.xml",
        )
        db.session.add(source)
        db.session.commit()
        app.extensions["dragon_feed_client"] = Client()

        operation = OperationCoordinator.run(kind="sync", domain="reading")

        article = db.session.scalar(db.select(Article))
        assert operation.status == "completed"
        assert operation.counts["created"] == 1
        assert article.title == "Fresh from the feed"
        assert source.health_state == "healthy"
