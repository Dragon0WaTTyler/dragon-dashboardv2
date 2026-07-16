import re

from flask import Response
from sqlalchemy import select

from app.extensions import db
from app.mytv.cache import query_cache
from app.mytv.models import (
    TVChannel,
    TVChannelHealth,
    TVChannelPreference,
    TVGroup,
    TVPlaylist,
    TVTheme,
)
from app.mytv.services import ChannelEntry, GithubTVSync
from app.mytv.streaming import StreamUnavailable

CSRF_META = re.compile(r'<meta name="csrf-token" content="([^"]+)">')


def seed_tv() -> tuple[int, int, int]:
    playlist = TVPlaylist(
        name="Test package",
        github_path="test.m3u",
        source_url="https://example.test/test.m3u",
        source_sha="seed",
        imported_sha="seed",
        size_bytes=100,
        imported=True,
        channel_count=2,
        group_count=1,
        sync_status="ready",
        enabled=True,
    )
    theme = TVTheme(key="news", name="News", enabled=True, channel_count=2, group_count=1)
    group = TVGroup(name="News", theme=theme, channel_count=2)
    playlist.groups.append(group)
    first = TVChannel(
        playlist=playlist,
        group=group,
        external_key="one",
        preference_key=ChannelEntry(
            "News One", "News", "https://stream.example/one.mp4", tvg_id="news.one"
        ).preference_key("news"),
        name="News One",
        tvg_id="news.one",
        stream_url="https://stream.example/one.mp4",
        stream_kind="file",
        position=1,
        last_seen_sync="seed",
    )
    second = TVChannel(
        playlist=playlist,
        group=group,
        external_key="two",
        preference_key=ChannelEntry(
            "News Two", "News", "https://stream.example/two.ts", tvg_id="news.two"
        ).preference_key("news"),
        name="News Two",
        tvg_id="news.two",
        stream_url="https://stream.example/two.ts",
        stream_kind="transport",
        enabled_override=False,
        position=2,
        last_seen_sync="seed",
    )
    db.session.add_all([playlist, first, second])
    db.session.commit()
    GithubTVSync.refresh_representatives()
    return playlist.id, theme.id, second.id


def csrf_header(client) -> dict[str, str]:
    page = client.get("/my-tv")
    match = CSRF_META.search(page.get_data(as_text=True))
    assert match is not None
    return {"X-CSRFToken": match.group(1)}


def test_mytv_requires_login(client):
    response = client.get("/my-tv")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_mytv_renders_inside_dragon_and_lists_enabled_channels(
    authenticated_client, app
):
    with app.app_context():
        seed_tv()
    page = authenticated_client.get("/my-tv")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "My TV" in html
    assert 'active_module="mytv"' not in html
    assert 'href="/my-tv" aria-current="page"' in html

    bootstrap = authenticated_client.get("/my-tv/api/bootstrap").get_json()
    assert bootstrap["stats"]["total_channels"] == 2
    assert bootstrap["stats"]["enabled_channels"] == 1
    channels = authenticated_client.get("/my-tv/api/channels?state=enabled").get_json()
    assert [item["name"] for item in channels["channels"]] == ["News One"]


def test_mytv_group_and_channel_overrides(authenticated_client, app):
    with app.app_context():
        _, group_id, channel_id = seed_tv()
    headers = csrf_header(authenticated_client)
    response = authenticated_client.patch(
        f"/my-tv/api/groups/{group_id}", json={"enabled": False}, headers=headers
    )
    assert response.status_code == 200
    assert authenticated_client.get("/my-tv/api/channels?state=enabled").get_json()[
        "pagination"
    ]["total"] == 0

    response = authenticated_client.patch(
        f"/my-tv/api/channels/{channel_id}", json={"enabled": True}, headers=headers
    )
    assert response.status_code == 200
    channels = authenticated_client.get("/my-tv/api/channels?state=enabled").get_json()
    assert [item["name"] for item in channels["channels"]] == ["News Two"]


def test_mytv_confirmed_offline_channels_are_hidden(authenticated_client, app):
    with app.app_context():
        _, _, _ = seed_tv()
        channel = db.session.scalar(
            select(TVChannel).where(TVChannel.name == "News One")
        )
        db.session.add(
            TVChannelHealth(
                preference_key=channel.preference_key,
                status="offline",
                failure_count=1,
                last_error="All source copies failed.",
            )
        )
        db.session.commit()
        query_cache.invalidate()

    channels = authenticated_client.get("/my-tv/api/channels?state=enabled").get_json()
    assert channels["pagination"]["total"] == 0
    bootstrap = authenticated_client.get("/my-tv/api/bootstrap").get_json()
    assert bootstrap["stats"]["enabled_channels"] == 0
    assert bootstrap["health"]["known_offline"] == 1


def test_mytv_health_check_route_is_protected_and_scoped(
    authenticated_client, app, monkeypatch
):
    with app.app_context():
        _, theme_id, _ = seed_tv()
    calls = []
    monkeypatch.setattr(
        "app.mytv.routes.health_coordinator.start",
        lambda _app, theme_id=None: calls.append(theme_id) or True,
    )
    response = authenticated_client.post(
        "/my-tv/api/health",
        json={"theme_id": theme_id},
        headers=csrf_header(authenticated_client),
    )
    assert response.status_code == 202
    assert calls == [theme_id]
    assert authenticated_client.post(
        "/my-tv/api/health", json={"theme_id": theme_id}
    ).status_code == 400


def test_mytv_active_selector_hides_disabled_smart_theme(authenticated_client, app):
    with app.app_context():
        _, theme_id, _ = seed_tv()
    active = authenticated_client.get("/my-tv/api/groups?active_only=1").get_json()
    assert [item["name"] for item in active["groups"]] == ["News"]
    assert [
        item["name"]
        for item in authenticated_client.get(
            "/my-tv/api/groups?visibility=on"
        ).get_json()["groups"]
    ] == ["News"]
    assert authenticated_client.get(
        "/my-tv/api/groups?visibility=off"
    ).get_json()["groups"] == []

    headers = csrf_header(authenticated_client)
    authenticated_client.patch(
        f"/my-tv/api/groups/{theme_id}", json={"enabled": False}, headers=headers
    )
    hidden = authenticated_client.get("/my-tv/api/groups?active_only=1").get_json()
    assert hidden["groups"] == []
    assert authenticated_client.get(
        "/my-tv/api/groups?visibility=on"
    ).get_json()["groups"] == []
    assert [
        item["name"]
        for item in authenticated_client.get(
            "/my-tv/api/groups?visibility=off"
        ).get_json()["groups"]
    ] == ["News"]
    assert authenticated_client.get(
        "/my-tv/api/groups?visibility=unknown"
    ).status_code == 400


def test_mytv_query_cache_hits_and_invalidates(authenticated_client, app):
    with app.app_context():
        _, theme_id, _ = seed_tv()
    first = authenticated_client.get("/my-tv/api/bootstrap")
    second = authenticated_client.get("/my-tv/api/bootstrap")
    assert first.headers["X-MyTV-Cache"] == "MISS"
    assert second.headers["X-MyTV-Cache"] == "HIT"

    authenticated_client.patch(
        f"/my-tv/api/groups/{theme_id}",
        json={"enabled": False},
        headers=csrf_header(authenticated_client),
    )
    refreshed = authenticated_client.get("/my-tv/api/bootstrap")
    assert refreshed.headers["X-MyTV-Cache"] == "MISS"


def test_mytv_sources_are_automatic_while_themes_default_off(app):
    with app.app_context():
        playlist = TVPlaylist(
            name="Default off",
            github_path="default-off.m3u",
            source_url="https://example.test/default-off.m3u",
        )
        theme = TVTheme(key="default-off", name="Default off")
        db.session.add_all([playlist, theme])
        db.session.flush()
        assert playlist.enabled is True
        assert theme.enabled is False


class FakePlaylistResponse:
    status_code = 200
    encoding = "utf-8"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def iter_lines(self, decode_unicode=True):
        assert decode_unicode is True
        return iter(
            [
                '#EXTINF:-1 tvg-id="news.two" tvg-name="News Two" '
                'group-title="News",News Two replacement',
                "https://replacement.example/news-two.ts",
            ]
        )


class FakePlaylistSession:
    def __init__(self):
        self.headers = {}

    def get(self, *_args, **_kwargs):
        return FakePlaylistResponse()


def test_mytv_favorite_and_override_follow_replacement_file(authenticated_client, app):
    with app.app_context():
        _, _, channel_id = seed_tv()
    headers = csrf_header(authenticated_client)
    authenticated_client.patch(
        f"/my-tv/api/channels/{channel_id}", json={"enabled": True}, headers=headers
    )
    favorite = authenticated_client.patch(
        f"/my-tv/api/channels/{channel_id}/favorite",
        json={"favorite": True},
        headers=headers,
    )
    assert favorite.status_code == 200

    with app.app_context():
        replacement = TVPlaylist(
            name="Replacement package",
            github_path="replacement.m3u",
            source_url="https://example.test/replacement.m3u",
            source_sha="replacement-sha",
        )
        db.session.add(replacement)
        db.session.commit()
        GithubTVSync(session=FakePlaylistSession()).import_playlist(replacement.id)
        imported = db.session.scalar(
            select(TVChannel).where(TVChannel.playlist_id == replacement.id)
        )
        preference = db.session.get(TVChannelPreference, imported.preference_key)
        assert imported.enabled_override is True
        assert preference.favorite is True
        assert preference.enabled_override is True

    favorites = authenticated_client.get(
        "/my-tv/api/channels?state=favorites"
    ).get_json()
    assert favorites["pagination"]["total"] == 1
    assert favorites["channels"][0]["favorite"] is True


class FakeCatalogResponse:
    status_code = 200

    def json(self):
        return [
            {
                "type": "file",
                "name": "test.m3u",
                "path": "test.m3u",
                "download_url": "https://example.test/test.m3u",
                "sha": "changed-sha",
                "size": 120,
            },
            {
                "type": "file",
                "name": "new.m3u",
                "path": "new.m3u",
                "download_url": "https://example.test/new.m3u",
                "sha": "new-sha",
                "size": 80,
            },
        ]


class FakeCatalogSession:
    def __init__(self):
        self.headers = {}

    def get(self, *_args, **_kwargs):
        return FakeCatalogResponse()


def test_mytv_fetch_detects_changed_import_without_erasing_choices(app):
    with app.app_context():
        playlist_id, theme_id, _ = seed_tv()
        sync = GithubTVSync(session=FakeCatalogSession())
        sync.discover()
        assert sync.changed_ids == [playlist_id]
        assert len(sync.new_ids) == 1
        assert sync.pending_ids == sync.new_ids
        assert db.session.get(TVPlaylist, playlist_id).enabled is True
        assert db.session.get(TVTheme, theme_id).enabled is True


def test_mytv_playback_url_privacy(authenticated_client, app):
    with app.app_context():
        _, _, channel_id = seed_tv()
    headers = csrf_header(authenticated_client)
    authenticated_client.patch(
        f"/my-tv/api/channels/{channel_id}", json={"enabled": True}, headers=headers
    )
    playback = authenticated_client.get(f"/my-tv/api/channels/{channel_id}/playback")
    assert playback.status_code == 200
    assert playback.get_json()["url"] == f"/my-tv/play/{channel_id}"
    assert "stream.example" not in playback.get_data(as_text=True)


def test_mytv_playback_uses_an_alternate_source_and_quarantines_failure(
    authenticated_client, app, monkeypatch
):
    with app.app_context():
        _, theme_id, _ = seed_tv()
        theme = db.session.get(TVTheme, theme_id)
        working = db.session.scalar(
            select(TVChannel).where(TVChannel.name == "News One")
        )
        alternate_playlist = TVPlaylist(
            name="Alternate package",
            github_path="alternate.m3u",
            source_url="https://example.test/alternate.m3u",
            source_sha="alternate",
            imported_sha="alternate",
            imported=True,
            sync_status="ready",
        )
        alternate_group = TVGroup(
            name="News alternate", theme=theme, channel_count=1
        )
        alternate_playlist.groups.append(alternate_group)
        failing = TVChannel(
            playlist=alternate_playlist,
            group=alternate_group,
            external_key="alternate-news-one",
            preference_key=working.preference_key,
            name=working.name,
            stream_url="https://dead.example/live.m3u8",
            stream_kind="hls",
            position=1,
            last_seen_sync="alternate",
        )
        db.session.add_all([alternate_playlist, failing])
        db.session.commit()
        GithubTVSync.refresh_representatives()
        failing_id = failing.id

    calls: list[str] = []

    def failed_transcode(url: str):
        calls.append(url)
        raise StreamUnavailable("offline")

    def working_proxy(url: str):
        calls.append(url)
        return Response(b"fallback-video", content_type="video/mp4")

    monkeypatch.setattr("app.mytv.routes.transcode_stream", failed_transcode)
    monkeypatch.setattr("app.mytv.routes.proxy_file", working_proxy)

    first = authenticated_client.get(f"/my-tv/play/{failing_id}")
    assert first.status_code == 200
    assert first.get_data() == b"fallback-video"
    assert first.headers["X-Dragon-TV-Source-Attempt"] == "2"
    assert calls == [
        "https://dead.example/live.m3u8",
        "https://stream.example/one.mp4",
    ]

    calls.clear()
    second = authenticated_client.get(f"/my-tv/play/{failing_id}")
    assert second.status_code == 200
    assert second.headers["X-Dragon-TV-Source-Attempt"] == "1"
    assert calls == ["https://stream.example/one.mp4"]

def test_mytv_writes_require_csrf(authenticated_client, app):
    with app.app_context():
        _, theme_id, _ = seed_tv()
    response = authenticated_client.patch(
        f"/my-tv/api/groups/{theme_id}", json={"enabled": False}
    )
    assert response.status_code == 400
