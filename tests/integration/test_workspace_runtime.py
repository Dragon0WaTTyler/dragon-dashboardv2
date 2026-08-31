from __future__ import annotations

from sqlalchemy import func, select

from app.admin.control_center import preference_store
from app.auth.models import PersonalWorkspace, User
from app.books.book_quotes import (
    BookQuotesSnapshot,
    BookQuotesSnapshotItem,
    BookQuotesSnapshotService,
    _book_quotes_client,
)
from app.books.clippings import (
    KindleClippingsOutboxItem,
    KindleClippingsSyncState,
    workspace_aware_clippings_store,
)
from app.books.kindle_sync import WorkspaceKindleSyncCredentialStore
from app.books.notion_sync import BookNotionSyncService
from app.extensions import db
from app.movies.external_library import notion_movie_provider
from app.movies.models import Movie, MovieCustomList
from app.vault.integrations import integration_settings, update_integration_settings
from app.vault.runtime import bind_workspace, runtime_for


def _workspace(app, *, username: str, workspace_id: str) -> PersonalWorkspace:
    with app.app_context():
        user = User(username=username, password_hash=workspace_id)
        db.session.add(user)
        db.session.flush()
        workspace = PersonalWorkspace(
            id=workspace_id,
            owner_user_id=user.id,
            remote_locator=f"drive-{workspace_id}",
            state="ready",
        )
        db.session.add(workspace)
        db.session.commit()
        return db.session.get(PersonalWorkspace, workspace_id)


def _add_movie_in_workspace(app, workspace: PersonalWorkspace) -> None:
    with app.test_request_context("/"):
        bind_workspace(workspace)
        movie = Movie(title=f"Movie for {workspace.id}", normalized_title=workspace.id)
        db.session.add(movie)
        db.session.flush()
        db.session.add(
            MovieCustomList(
                owner_user_id=workspace.owner_user_id,
                title="Watch later",
            )
        )
        db.session.commit()
        db.session.remove()


def test_google_workspace_runtime_routes_content_to_isolated_sqlite_caches(app):
    first = _workspace(app, username="first-google-user", workspace_id="workspace_first")
    second = _workspace(app, username="second-google-user", workspace_id="workspace_second")

    _add_movie_in_workspace(app, first)
    _add_movie_in_workspace(app, second)

    with app.app_context():
        # The central authentication database did not receive personal content.
        assert db.session.scalar(select(func.count()).select_from(Movie)) == 0

        runtime = runtime_for(app)
        first_engine = runtime.engine_for(
            bind_workspace_for_test(first, app)
        )
        second_engine = runtime.engine_for(
            bind_workspace_for_test(second, app)
        )
        with first_engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(Movie.__table__)) == 1
            assert (
                connection.scalar(select(func.count()).select_from(MovieCustomList.__table__))
                == 1
            )
        with second_engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(Movie.__table__)) == 1
            assert (
                connection.scalar(select(func.count()).select_from(MovieCustomList.__table__))
                == 1
            )


def test_workspace_integration_settings_are_private_and_portable(app):
    first = _workspace(app, username="first-config-user", workspace_id="workspace_config_one")
    second = _workspace(app, username="second-config-user", workspace_id="workspace_config_two")

    with app.test_request_context("/"):
        bind_workspace(first)
        update_integration_settings(
            "notion",
            {
                "token": "workspace-only-token",
                "database_id": "notion-movies-one",
                "book_data_source_id": "notion-books-one",
                "book_quotes_database_id": "notion-book-quotes-one",
            },
        )
        assert integration_settings("notion")["book_data_source_id"] == "notion-books-one"
        client = BookNotionSyncService._client()
        assert client is not None
        assert client.token == "workspace-only-token"
        assert client._configured_data_source_id == "notionbooksone"
        movie_provider = notion_movie_provider()
        assert movie_provider.token == "workspace-only-token"
        assert movie_provider.database_id == "notionmoviesone"
        quotes_client = _book_quotes_client()
        assert quotes_client.token == "workspace-only-token"
        assert quotes_client.target_id == "notionbookquotesone"
        BookQuotesSnapshotService.store().save(
            BookQuotesSnapshot(
                items=(
                    BookQuotesSnapshotItem(
                        notion_page_id="quote-one",
                        payload={"quote": "First workspace only"},
                    ),
                )
            )
        )
        workspace_aware_clippings_store("unused-for-personal-workspaces").save(
            KindleClippingsSyncState(
                pending=(
                    KindleClippingsOutboxItem(
                        unique_hash="kindle-one",
                        payload={"quote": "Personal Kindle clipping"},
                    ),
                )
            )
        )
        preference_store().set_movie_preferences(
            {
                "autoplay_next": False,
                "automatic_resume": True,
                "default_subtitle_language": "fr",
                "preferred_audio_language": "original",
                "preferred_quality": "1080p",
                "preferred_source": "vidsrc",
                "preferred_region": "MA",
                "reduced_effects": True,
                "ambient_level": "normal",
            }
        )
        db.session.remove()

    with app.test_request_context("/"):
        bind_workspace(second)
        assert integration_settings("notion") == {}
        assert BookQuotesSnapshotService.store().load().items == ()
        assert workspace_aware_clippings_store("unused").load().pending == ()
        assert preference_store().read()["sections"]["movies"]["movie_preferences"][
            "preferred_region"
        ] == "US"

    with app.test_request_context("/"):
        bind_workspace(first)
        assert BookQuotesSnapshotService.store().load().items[0].notion_page_id == "quote-one"
        assert (
            workspace_aware_clippings_store("unused").load().pending[0].unique_hash
            == "kindle-one"
        )
        assert preference_store().read()["sections"]["movies"]["movie_preferences"] == {
            "autoplay_next": False,
            "automatic_resume": True,
            "default_subtitle_language": "fr",
            "preferred_audio_language": "original",
            "preferred_quality": "1080p",
            "preferred_source": "vidsrc",
            "preferred_region": "MA",
            "reduced_effects": True,
            "ambient_level": "normal",
        }


def test_personal_kindle_sync_uses_only_its_workspace_notion_connection(app):
    first = _workspace(app, username="kindle-config-one", workspace_id="workspace_kindle_one")
    second = _workspace(app, username="kindle-config-two", workspace_id="workspace_kindle_two")

    with app.test_request_context("/"):
        bind_workspace(first)
        update_integration_settings(
            "notion",
            {
                "token": "first-workspace-token",
                "book_quotes_data_source_id": "first-book-quotes-source",
            },
        )
        readiness = WorkspaceKindleSyncCredentialStore().status()
        assert readiness.token_configured is True
        assert readiness.target_id_configured is True
        assert readiness.destination_label == "Personal Book Quotes"
        assert BookQuotesSnapshotService.status()["configured"] is True
        db.session.remove()

    with app.test_request_context("/"):
        bind_workspace(second)
        readiness = WorkspaceKindleSyncCredentialStore().status()
        assert readiness.token_configured is False
        assert readiness.target_id_configured is False
        assert BookQuotesSnapshotService.status()["configured"] is False


def test_personal_kindle_upload_never_falls_back_to_shared_credentials(app, monkeypatch):
    first = _workspace(app, username="kindle-upload-one", workspace_id="workspace_upload_one")
    second = _workspace(app, username="kindle-upload-two", workspace_id="workspace_upload_two")
    calls: list[tuple[str, str, str]] = []

    class FakeBookQuotesClient:
        def __init__(self, *, token, target_kind, target_id, **kwargs):
            calls.append((token, target_kind, target_id))

        def has_existing_hash(self, unique_hash):
            return False

        def create_quote_page(self, item, *, imported_at):
            assert item.unique_hash == "personal-kindle-quote"
            assert imported_at

    monkeypatch.setattr("app.books.kindle_sync.KindleBookQuotesClient", FakeBookQuotesClient)
    state = KindleClippingsSyncState(
        pending=(
            KindleClippingsOutboxItem(
                unique_hash="personal-kindle-quote",
                payload={"quote": "Only the owner can upload this."},
            ),
        )
    )

    with app.test_request_context("/"):
        bind_workspace(first)
        update_integration_settings(
            "notion",
            {
                "token": "owner-notion-token",
                "book_quotes_database_id": "owner-book-quotes-db",
            },
        )
        result = WorkspaceKindleSyncCredentialStore().sync_pending(state)
        assert result.uploaded == 1
        assert result.failed == 0
        assert calls == [("owner-notion-token", "database", "owner-book-quotes-db")]
        db.session.remove()

    with app.test_request_context("/"):
        bind_workspace(second)
        result = WorkspaceKindleSyncCredentialStore().sync_pending(state)
        assert result.uploaded == 0
        assert result.failed == 1
        assert calls == [("owner-notion-token", "database", "owner-book-quotes-db")]


def bind_workspace_for_test(workspace: PersonalWorkspace, app):
    return runtime_for(app).bind(workspace)
