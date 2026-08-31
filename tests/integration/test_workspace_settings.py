from __future__ import annotations

import json
from io import BytesIO

from sqlalchemy import select

from app.auth.models import PersonalWorkspace, User
from app.extensions import db
from app.vault.integrations import integration_settings
from app.vault.runtime import bind_workspace
from app.youtube.models import PocketTubeChannelMembership, YouTubeVideo
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
            "book_quotes_notion_database_id": "notion-book-quotes",
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
            "book_quotes_database_id": "notion-book-quotes",
        }


def test_personal_workspace_imports_its_own_pockettube_export(client, app):
    with app.app_context():
        user = User(username="pockettube-workspace-user", password_hash="")
        user.set_password("pockettube-workspace-password")
        db.session.add(user)
        db.session.flush()
        workspace = PersonalWorkspace(
            id="workspace_pockettube_test",
            owner_user_id=user.id,
            remote_locator="drive-workspace-pockettube",
            state="ready",
        )
        db.session.add(workspace)
        db.session.commit()
        workspace_id = workspace.id

        class PlaylistClient:
            def fetch_channel_uploads(self, channel_limits, *, maximum):
                assert channel_limits == {"UCchannel111111": 200}
                assert maximum == 10000
                return {
                    "UCchannel111111": [
                        {
                            "id": "upload-one",
                            "snippet": {
                                "title": "Personal channel upload",
                                "resourceId": {"videoId": "video-one"},
                                "channelTitle": "Personal Channel",
                                "publishedAt": "2026-08-31T00:00:00Z",
                            },
                        }
                    ]
                }

            def fetch_durations(self, video_ids, *, maximum):
                assert video_ids == ["video-one"]
                return {"video-one": 600}

        app.extensions["dragon_youtube_playlist_client"] = PlaylistClient()

    signed_in = login(client, "pockettube-workspace-user", "pockettube-workspace-password")
    assert signed_in.status_code == 302
    workspace_page = client.get("/auth/workspace")
    settings_response = client.post(
        "/auth/workspace",
        data={
            "csrf_token": csrf_from(workspace_page),
            "youtube_api_key": "workspace-youtube-key",
            "youtube_playlist_id": "PL-workspace-playlist",
        },
        follow_redirects=False,
    )
    assert settings_response.status_code == 302

    pockettube_page = client.get("/youtube?source=pockettube")
    assert b'name="export"' in pockettube_page.data
    assert b"Import PocketTube export" in pockettube_page.data
    response = client.post(
        "/youtube/sync-pockettube",
        data={
            "csrf_token": csrf_from(pockettube_page),
            "return_to": "/youtube?source=pockettube",
            "export": (
                BytesIO(json.dumps({"Personal feeds": ["UCchannel111111"]}).encode()),
                "pockettube.json",
            ),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    with app.test_request_context("/"):
        workspace = db.session.scalar(
            select(PersonalWorkspace).where(PersonalWorkspace.id == workspace_id)
        )
        assert workspace is not None
        bind_workspace(workspace)
        assert db.session.scalar(select(YouTubeVideo.title)) == "Personal channel upload"
        assert (
            db.session.scalar(select(PocketTubeChannelMembership.channel_id))
            == "UCchannel111111"
        )
