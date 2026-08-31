from __future__ import annotations

from sqlalchemy import select

from app.auth.models import PersonalWorkspace, User
from app.extensions import db
from app.vault.integrations import integration_settings
from app.vault.runtime import bind_workspace
from tests.conftest import csrf_from, login


def test_workspace_page_offers_a_clear_google_connection_state(authenticated_client):
    response = authenticated_client.get("/auth/workspace")

    assert response.status_code == 200
    assert b"Google Drive connection is not configured" in response.data


def test_workspace_page_saves_youtube_and_notion_settings_in_the_private_cache(client, app):
    with app.app_context():
        user = User(username="workspace-settings-user", password_hash="")
        user.set_password("workspace-settings-password")
        db.session.add(user)
        db.session.flush()
        workspace = PersonalWorkspace(
            id="workspace_settings_test",
            owner_user_id=user.id,
            remote_locator="drive-workspace-settings",
            state="ready",
        )
        db.session.add(workspace)
        db.session.commit()
        workspace_id = workspace.id

    signed_in = login(client, "workspace-settings-user", "workspace-settings-password")
    assert signed_in.status_code == 302
    page = client.get("/auth/workspace")
    response = client.post(
        "/auth/workspace",
        data={
            "csrf_token": csrf_from(page),
            "youtube_api_key": "youtube-private-key",
            "youtube_playlist_id": "PL-private-playlist",
            "notion_token": "notion-private-token",
            "notion_database_id": "notion-movies",
            "book_notion_database_id": "notion-books",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert b"youtube-private-key" not in client.get("/auth/workspace").data
    with app.test_request_context("/auth/workspace"):
        workspace = db.session.scalar(
            select(PersonalWorkspace).where(PersonalWorkspace.id == workspace_id)
        )
        assert workspace is not None
        bind_workspace(workspace)
        assert integration_settings("youtube") == {
            "api_key": "youtube-private-key",
            "playlist_id": "PL-private-playlist",
        }
        assert integration_settings("notion") == {
            "token": "notion-private-token",
            "database_id": "notion-movies",
            "book_database_id": "notion-books",
        }
