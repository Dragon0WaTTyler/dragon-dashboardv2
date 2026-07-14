from app.extensions import db
from app.shared.models import Operation
from app.shared.operations import OperationService
from app.shared.refresh import OperationCoordinator
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
