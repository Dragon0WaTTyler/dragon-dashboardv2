from __future__ import annotations

import gc
import shutil
import time
from dataclasses import dataclass

import pytest
from sqlalchemy import select

from app.admin.control_center import preference_store
from app.auth.models import PersonalWorkspace, User, WorkspaceConnection
from app.books.models import Book
from app.extensions import db
from app.movies.models import Movie, MovieCustomList, MovieProgress
from app.reading.models import ReadingSource
from app.vault.crypto import encrypt_payload
from app.vault.google import (
    WORKSPACE_CACHE_FILENAME,
    DriveFile,
    GoogleVaultConflictError,
)
from app.vault.integrations import integration_settings, update_integration_settings
from app.vault.runtime import runtime_for
from app.youtube.models import PocketTubeChannelMembership, YouTubeVideo


@dataclass
class FakeGoogleWorkspaceCache:
    file: DriveFile | None = None
    contents: bytes = b""
    uploads: int = 0
    downloads: int = 0

    def refresh_access_token(self, *, refresh_token: str) -> str:
        assert refresh_token == "refresh-token"
        return "access-token"

    def find_appdata_file(self, *, access_token: str, name: str) -> DriveFile | None:
        assert access_token == "access-token"
        assert name == WORKSPACE_CACHE_FILENAME
        return self.file

    def download_appdata_file(
        self, *, access_token: str, file: DriveFile
    ) -> tuple[bytes, DriveFile]:
        assert access_token == "access-token"
        assert file == self.file
        self.downloads += 1
        return self.contents, file

    def upload_appdata_file(
        self,
        *,
        access_token: str,
        name: str,
        contents: bytes,
        current: DriveFile | None = None,
    ) -> DriveFile:
        assert access_token == "access-token"
        assert name == WORKSPACE_CACHE_FILENAME
        assert current is None or current == self.file
        self.uploads += 1
        self.contents = contents
        self.file = DriveFile(
            id="cache-file",
            name=name,
            version=str(self.uploads),
            etag=f"etag-{self.uploads}",
        )
        return self.file


def _remove_workspace_cache(path) -> None:
    """Windows can release a disposed SQLite handle a moment after teardown."""

    for attempt in range(10):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            gc.collect()
            time.sleep(0.05)


def test_workspace_cache_initializes_from_drive_and_saves_personal_content(app):
    client = FakeGoogleWorkspaceCache()
    app.extensions["dragon_google_oauth_client"] = client
    app.config["DRAGON_GOOGLE_PERSONAL_VAULT_SYNC_ENABLED"] = True

    with app.app_context():
        user = User(username="google-cache-user", password_hash="")
        user.set_password("temporary-test-password")
        db.session.add(user)
        db.session.flush()
        db.session.add(Movie(title="Legacy local movie", normalized_title="legacy local movie"))
        workspace = PersonalWorkspace(
            id="workspace_cache_test",
            owner_user_id=user.id,
            remote_locator="manifest-file",
            state="needs_seed",
        )
        db.session.add(workspace)
        db.session.add(
            WorkspaceConnection(
                workspace_id=workspace.id,
                provider="google_drive",
                credential_ciphertext=encrypt_payload(
                    app.config["SECRET_KEY"],
                    {"refresh_token": "refresh-token"},
                ),
                scopes=[],
            )
        )
        db.session.commit()
        workspace_id = workspace.id

    with app.test_request_context("/movies"):
        workspace = db.session.get(PersonalWorkspace, workspace_id)
        assert workspace is not None
        runtime = runtime_for(app)
        binding = runtime.prepare_google_sync(workspace)
        legacy_movie = db.session.scalar(select(Movie).where(Movie.title == "Legacy local movie"))
        assert legacy_movie is not None
        saved_movie = Movie(
            title="Saved in Drive",
            normalized_title="saved in drive",
            status="want_to_watch",
        )
        db.session.add(saved_movie)
        db.session.flush()
        db.session.add(
            MovieProgress(
                movie_id=saved_movie.id,
                current_seconds=842,
                duration_seconds=2400,
            )
        )
        db.session.add(
            MovieCustomList(
                owner_user_id=workspace.owner_user_id,
                title="I want to watch",
            )
        )
        db.session.add(
            ReadingSource(
                name="Owner RSS",
                feed_url="https://feeds.example.test/owner.xml",
                category="technology",
            )
        )
        db.session.add(
            PocketTubeChannelMembership(
                group_name="Owner channels",
                channel_id="UC-owner-channel",
                catalogue_depth=12,
            )
        )
        db.session.add(
            YouTubeVideo(
                external_id="owner-pockettube-video",
                source="pockettube",
                group_name="Owner channels",
                channel_id="UC-owner-channel",
                channel_title="Owner channel",
                title="PocketTube video owned by this workspace",
                watched=True,
            )
        )
        db.session.add(
            Book(
                title="A workspace-owned book",
                normalized_title="a workspace-owned book",
                authors=["Owner"],
                status="reading",
                current_page=73,
                page_count=320,
            )
        )
        update_integration_settings(
            "youtube",
            {
                "api_key": "workspace-youtube-key",
                "playlist_id": "PL-workspace-playlist",
            },
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
        db.session.commit()
        assert runtime.finalize_google_sync() == "saved"
        db.session.remove()

    assert client.uploads == 2
    assert client.contents.startswith(b"SQLite format 3")

    # A fresh local installation restores the same personal content from Drive.
    runtime.dispose()
    _remove_workspace_cache(binding.cache_path.parent)
    with app.test_request_context("/movies"):
        workspace = db.session.get(PersonalWorkspace, workspace_id)
        assert workspace is not None
        assert workspace.state == "ready"
        runtime = runtime_for(app)
        runtime.prepare_google_sync(workspace)
        restored = db.session.scalar(select(Movie).where(Movie.title == "Saved in Drive"))
        assert restored is not None
        progress = db.session.scalar(
            select(MovieProgress).where(MovieProgress.movie_id == restored.id)
        )
        assert progress is not None
        assert (progress.current_seconds, progress.duration_seconds) == (842, 2400)
        assert db.session.scalar(select(MovieCustomList.title)) == "I want to watch"
        source = db.session.scalar(
            select(ReadingSource).where(ReadingSource.name == "Owner RSS")
        )
        assert source is not None
        assert source.feed_url == "https://feeds.example.test/owner.xml"
        membership = db.session.scalar(
            select(PocketTubeChannelMembership).where(
                PocketTubeChannelMembership.channel_id == "UC-owner-channel"
            )
        )
        assert membership is not None
        assert membership.group_name == "Owner channels"
        video = db.session.scalar(
            select(YouTubeVideo).where(YouTubeVideo.external_id == "owner-pockettube-video")
        )
        assert video is not None
        assert video.watched is True
        book = db.session.scalar(select(Book).where(Book.title == "A workspace-owned book"))
        assert book is not None
        assert (book.status, book.current_page, book.page_count) == ("reading", 73, 320)
        assert integration_settings("youtube") == {
            "api_key": "workspace-youtube-key",
            "playlist_id": "PL-workspace-playlist",
        }
        assert preference_store().read()["sections"]["movies"]["movie_preferences"][
            "preferred_region"
        ] == "MA"


def test_workspace_sync_uses_matching_version_when_drive_etag_is_empty(app):
    client = FakeGoogleWorkspaceCache(
        file=DriveFile(
            id="cache-file",
            name=WORKSPACE_CACHE_FILENAME,
            version="1",
            etag="",
        )
    )
    app.extensions["dragon_google_oauth_client"] = client

    with app.app_context():
        user = User(username="google-version-user", password_hash="")
        user.set_password("temporary-test-password")
        db.session.add(user)
        db.session.flush()
        workspace = PersonalWorkspace(
            id="workspace_version_test",
            owner_user_id=user.id,
            remote_locator="manifest-file",
            state="ready",
        )
        db.session.add(workspace)
        db.session.add(
            WorkspaceConnection(
                workspace_id=workspace.id,
                provider="google_drive",
                credential_ciphertext=encrypt_payload(
                    app.config["SECRET_KEY"],
                    {"refresh_token": "refresh-token"},
                ),
                scopes=[],
            )
        )
        db.session.commit()
        workspace_id = workspace.id

    with app.test_request_context("/movies"):
        workspace = db.session.get(PersonalWorkspace, workspace_id)
        assert workspace is not None
        runtime = runtime_for(app)
        binding = runtime.bind(workspace)
        runtime._write_sync_state(
            binding,
            {
                "remote_version": "1",
                "remote_etag": "",
                "dirty": False,
                "conflict": False,
            },
        )

        runtime.prepare_google_sync(workspace)

    assert client.downloads == 0


def test_workspace_sync_preserves_dirty_local_cache_when_drive_changed(app):
    client = FakeGoogleWorkspaceCache(
        file=DriveFile(
            id="cache-file",
            name=WORKSPACE_CACHE_FILENAME,
            version="2",
            etag="etag-2",
        )
    )
    app.extensions["dragon_google_oauth_client"] = client

    with app.app_context():
        user = User(username="google-conflict-user", password_hash="")
        user.set_password("temporary-test-password")
        db.session.add(user)
        db.session.flush()
        workspace = PersonalWorkspace(
            id="workspace_conflict_test",
            owner_user_id=user.id,
            remote_locator="manifest-file",
            state="ready",
        )
        db.session.add(workspace)
        db.session.add(
            WorkspaceConnection(
                workspace_id=workspace.id,
                provider="google_drive",
                credential_ciphertext=encrypt_payload(
                    app.config["SECRET_KEY"],
                    {"refresh_token": "refresh-token"},
                ),
                scopes=[],
            )
        )
        db.session.commit()
        workspace_id = workspace.id

    with app.test_request_context("/movies"):
        workspace = db.session.get(PersonalWorkspace, workspace_id)
        assert workspace is not None
        runtime = runtime_for(app)
        binding = runtime.bind(workspace)
        runtime._write_sync_state(
            binding,
            {
                "remote_version": "1",
                "remote_etag": "etag-1",
                "dirty": True,
                "conflict": False,
            },
        )

        with pytest.raises(GoogleVaultConflictError, match="unsynchronised local changes"):
            runtime.prepare_google_sync(workspace)
