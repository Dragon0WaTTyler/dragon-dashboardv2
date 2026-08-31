from __future__ import annotations

import shutil
from dataclasses import dataclass

from sqlalchemy import select

from app.auth.models import PersonalWorkspace, User, WorkspaceConnection
from app.extensions import db
from app.movies.models import Movie, MovieCustomList, MovieProgress
from app.vault.crypto import encrypt_payload
from app.vault.google import WORKSPACE_CACHE_FILENAME, DriveFile
from app.vault.runtime import runtime_for


@dataclass
class FakeGoogleWorkspaceCache:
    file: DriveFile | None = None
    contents: bytes = b""
    uploads: int = 0

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
        db.session.commit()
        assert runtime.finalize_google_sync() == "saved"
        db.session.remove()

    assert client.uploads == 2
    assert client.contents.startswith(b"SQLite format 3")

    # A fresh local installation restores the same personal content from Drive.
    runtime.dispose()
    shutil.rmtree(binding.cache_path.parent)
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
