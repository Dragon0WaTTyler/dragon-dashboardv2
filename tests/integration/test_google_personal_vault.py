from __future__ import annotations

from sqlalchemy import select

from app.auth.models import ExternalIdentity, PersonalWorkspace, User, WorkspaceConnection
from app.extensions import db
from app.vault.crypto import decrypt_payload
from app.vault.google import VaultReference
from app.vault.services import GoogleWorkspaceService


class FakeGoogleOAuthClient:
    def redirect_uri(self, fallback: str) -> str:
        return fallback

    def authorization_url(self, *, redirect_uri: str, state: str) -> str:
        return f"https://accounts.example.test/authorize?state={state}&redirect_uri={redirect_uri}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> dict[str, str]:
        assert code == "approved-code"
        assert redirect_uri.endswith("/auth/google/callback")
        return {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "scope": "openid email profile https://www.googleapis.com/auth/drive.appdata",
        }

    def identity(self, *, access_token: str) -> dict[str, str]:
        assert access_token == "access-token"
        return {
            "subject": "google-subject-42",
            "email": "person@example.test",
            "display_name": "A Dragon User",
        }

    def locate_vault(self, *, access_token: str) -> VaultReference | None:
        assert access_token == "access-token"
        return None

    def create_vault(self, *, access_token: str, workspace_id: str) -> VaultReference:
        assert access_token == "access-token"
        assert workspace_id.startswith("workspace_")
        return VaultReference(file_id="drive-file-42", workspace_id=workspace_id)


def _enable_google_vault(app) -> None:
    app.config.update(
        DRAGON_GOOGLE_OAUTH_ENABLED=True,
        DRAGON_GOOGLE_PERSONAL_VAULT_LOGIN_ENABLED=True,
    )
    app.extensions["dragon_google_oauth_client"] = FakeGoogleOAuthClient()


def test_google_login_is_hidden_and_unroutable_until_explicitly_enabled(client):
    assert b"Continue with Google" not in client.get("/auth/login").data
    assert client.get("/auth/google").status_code == 404


def test_google_login_creates_an_encrypted_personal_drive_workspace(client, app):
    _enable_google_vault(app)

    login_page = client.get("/auth/login")
    assert b"Continue with Google" in login_page.data

    started = client.get("/auth/google?next=/movies", follow_redirects=False)
    assert started.status_code == 302
    with client.session_transaction() as session:
        state = session["google_oauth_state"]

    completed = client.get(
        f"/auth/google/callback?code=approved-code&state={state}",
        follow_redirects=False,
    )
    assert completed.status_code == 302
    assert completed.headers["Location"] == "/movies"

    with app.app_context():
        user = db.session.scalar(select(User).where(User.username.startswith("google-")))
        assert user is not None
        identity = db.session.scalar(
            select(ExternalIdentity).where(ExternalIdentity.user_id == user.id)
        )
        assert identity is not None
        assert identity.email == "person@example.test"
        workspace = db.session.scalar(
            select(PersonalWorkspace).where(PersonalWorkspace.owner_user_id == user.id)
        )
        assert workspace is not None
        assert workspace.storage_provider == "google_drive"
        assert workspace.remote_locator == "drive-file-42"
        connection = db.session.scalar(
            select(WorkspaceConnection).where(WorkspaceConnection.workspace_id == workspace.id)
        )
        assert connection is not None
        assert "refresh-token" not in connection.credential_ciphertext
        assert decrypt_payload(app.config["SECRET_KEY"], connection.credential_ciphertext) == {
            "refresh_token": "refresh-token",
            "google_subject": "google-subject-42",
            "vault_file_id": "drive-file-42",
        }


def test_google_connection_reuses_the_canonical_workspace_id_from_drive(app):
    class ExistingVaultClient(FakeGoogleOAuthClient):
        def locate_vault(self, *, access_token: str) -> VaultReference | None:
            assert access_token == "access-token"
            return VaultReference(
                file_id="drive-file-existing",
                workspace_id="workspace_shared_42",
            )

    with app.app_context():
        user = GoogleWorkspaceService.connect(
            client=ExistingVaultClient(),
            secret_key=app.config["SECRET_KEY"],
            token_payload={"access_token": "access-token", "refresh_token": "refresh-token"},
            identity_payload={
                "subject": "google-subject-existing",
                "email": "second-device@example.test",
                "display_name": "Second Device",
            },
        )
        workspace = db.session.scalar(
            select(PersonalWorkspace).where(PersonalWorkspace.owner_user_id == user.id)
        )
        assert workspace is not None
        assert workspace.id == "workspace_shared_42"
        assert workspace.remote_locator == "drive-file-existing"
