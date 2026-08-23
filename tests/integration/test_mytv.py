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
    TVSource,
    TVTheme,
    TVThemePreference,
)
from app.mytv.services import (
    ChannelEntry,
    GithubTVSync,
    persist_theme_preference,
    prune_irrelevant_playlist_cache,
    purge_unavailable_playlists,
    relevant_playlist_ids,
)
from app.mytv.source_manager import TVSourceManager

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
    assert 'id="groupFilter"' not in html
    assert 'class="field tv-visibility-filter"' in html
    assert 'id="channelSearch"' in html
    assert "Quick control" not in html
    assert 'id="channelGrid" role="list"' in html
    assert 'id="previousPage"' not in html
    assert 'id="nextPage"' not in html
    assert 'id="manageChannelList" role="list"' in html
    assert 'id="manageChannelSearch"' in html
    assert "Channel exceptions" in html
    assert 'data-channel-view="favorites"' in html
    assert 'id="refreshEpg"' in html
    assert 'id="loadMoreChannels"' in html

    bootstrap = authenticated_client.get("/my-tv/api/bootstrap").get_json()
    assert bootstrap["stats"]["total_channels"] == 2
    assert bootstrap["stats"]["enabled_channels"] == 1
    channels = authenticated_client.get("/my-tv/api/channels?state=enabled").get_json()
    assert [item["name"] for item in channels["channels"]] == ["News One"]


def test_primary_tv_catalogue_can_be_reconfigured_from_settings(authenticated_client, app):
    response = authenticated_client.post(
        "/admin/sections/mytv/builtin-source",
        data={
            "csrf_token": csrf_header(authenticated_client)["X-CSRFToken"],
            "source_id": 1,
            "locator": "example-owner/example-tv",
            "branch": "playlists",
            "refresh_interval_minutes": "60",
            "enabled": "on",
            "auto_refresh": "on",
            "submit_action": "save",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Primary TV catalogue settings saved." in response.get_data(as_text=True)
    with app.app_context():
        source = db.session.get(TVSource, 1)
        assert source is not None
        assert source.locator == "example-owner/example-tv"
        assert source.branch == "playlists"
        assert source.refresh_interval_minutes == 60
    lineup = authenticated_client.get("/my-tv").get_data(as_text=True)
    assert "https://github.com/example-owner/example-tv" in lineup


def test_mytv_group_and_channel_overrides(authenticated_client, app):
    with app.app_context():
        _, group_id, channel_id = seed_tv()
    headers = csrf_header(authenticated_client)
    response = authenticated_client.patch(
        f"/my-tv/api/groups/{group_id}", json={"enabled": False}, headers=headers
    )
    assert response.status_code == 200
    with app.app_context():
        durable_theme = db.session.get(TVThemePreference, "news")
        assert durable_theme.enabled is False
    assert authenticated_client.get("/my-tv/api/channels?state=enabled").get_json()[
        "pagination"
    ]["total"] == 0

    response = authenticated_client.patch(
        f"/my-tv/api/channels/{channel_id}", json={"enabled": True}, headers=headers
    )
    assert response.status_code == 200
    channels = authenticated_client.get("/my-tv/api/channels?state=enabled").get_json()
    assert [item["name"] for item in channels["channels"]] == ["News Two"]

    response = authenticated_client.patch(
        f"/my-tv/api/channels/{channel_id}", json={"enabled": None}, headers=headers
    )
    assert response.status_code == 200
    all_channels = authenticated_client.get("/my-tv/api/channels?state=all").get_json()
    restored = next(item for item in all_channels["channels"] if item["id"] == channel_id)
    assert restored["enabled_override"] is None
    with app.app_context():
        channel = db.session.get(TVChannel, channel_id)
        assert db.session.get(TVChannelPreference, channel.preference_key) is None


def test_mytv_bulk_change_can_be_undone(authenticated_client, app):
    with app.app_context():
        _, group_id, channel_id = seed_tv()
    headers = csrf_header(authenticated_client)
    authenticated_client.patch(
        f"/my-tv/api/channels/{channel_id}", json={"enabled": True}, headers=headers
    )
    with app.app_context():
        channel = db.session.get(TVChannel, channel_id)
        db.session.delete(db.session.get(TVChannelPreference, channel.preference_key))
        db.session.commit()

    changed = authenticated_client.post(
        f"/my-tv/api/groups/{group_id}/channels",
        json={"action": "disable"},
        headers=headers,
    )
    assert changed.status_code == 200
    payload = changed.get_json()
    assert payload["affected_channels"] == 2
    assert payload["undo_seconds"] == 20
    assert authenticated_client.get("/my-tv/api/channels?state=enabled").get_json()[
        "pagination"
    ]["total"] == 0

    restored = authenticated_client.post(
        f"/my-tv/api/groups/{group_id}/channels/undo",
        json={"token": payload["undo_token"]},
        headers=headers,
    )
    assert restored.status_code == 200
    enabled = authenticated_client.get("/my-tv/api/channels?state=enabled").get_json()
    assert {item["name"] for item in enabled["channels"]} == {"News One", "News Two"}
    with app.app_context():
        channel = db.session.get(TVChannel, channel_id)
        assert (
            db.session.get(TVChannelPreference, channel.preference_key).enabled_override
            is True
        )
    assert (
        authenticated_client.post(
            f"/my-tv/api/groups/{group_id}/channels/undo",
            json={"token": payload["undo_token"]},
            headers=headers,
        ).status_code
        == 409
    )


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


def test_mytv_epg_route_is_protected_and_reports_status(
    authenticated_client, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        "app.mytv.routes.epg_coordinator.start",
        lambda _app, force=False, tvg_ids=None: calls.append((force, tvg_ids)) or True,
    )
    status = authenticated_client.get("/my-tv/api/epg")
    assert status.status_code == 200
    assert "state" in status.get_json()
    started = authenticated_client.post(
        "/my-tv/api/epg", json={}, headers=csrf_header(authenticated_client)
    )
    assert started.status_code == 202
    assert calls == [(True, None)]
    assert authenticated_client.post("/my-tv/api/epg", json={}).status_code == 400


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
        "/my-tv/api/channels?state=all&active_only=true"
    ).get_json()["channels"] == []
    assert len(
        authenticated_client.get("/my-tv/api/channels?state=all").get_json()[
            "channels"
        ]
    ) == 2
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


class MappedPlaylistResponse(FakePlaylistResponse):
    def iter_lines(self, decode_unicode=True):
        assert decode_unicode is True
        return iter(
            [
                '#EXTINF:-1 tvg-name="AR: AL JAZEERA" group-title="News",AR: AL JAZEERA',
                "https://replacement.example/al-jazeera.ts",
            ]
        )


class MappedPlaylistSession(FakePlaylistSession):
    def get(self, *_args, **_kwargs):
        return MappedPlaylistResponse()


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


def test_mytv_import_repairs_epg_metadata_and_preserves_existing_favorite(app):
    with app.app_context():
        old_preference = TVChannelPreference(
            preference_key=ChannelEntry("AR: AL JAZEERA", "news", "").preference_key("news"),
            theme_key="news",
            name="AR: AL JAZEERA",
            tvg_id="",
            favorite=True,
        )
        playlist = TVPlaylist(
            name="Mapped package",
            github_path="mapped.m3u",
            source_url="https://example.test/mapped.m3u",
            source_sha="mapped-sha",
        )
        db.session.add_all([old_preference, playlist])
        db.session.commit()

        GithubTVSync(session=MappedPlaylistSession()).import_playlist(playlist.id)

        imported = db.session.scalar(select(TVChannel).where(TVChannel.playlist_id == playlist.id))
        preference = db.session.get(TVChannelPreference, imported.preference_key)
        assert imported.tvg_id == "Al.Jazeera.HD.ae"
        assert preference.favorite is True
        assert preference.tvg_id == "Al.Jazeera.HD.ae"


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


class FakeNestedCatalogResponse:
    status_code = 200

    def json(self):
        return {
            "tree": [
                {
                    "type": "blob",
                    "path": "dist/cleaned-playlist.m3u",
                    "sha": "dist-sha",
                    "size": 480,
                },
                {"type": "blob", "path": "README.md", "sha": "readme", "size": 12},
            ]
        }


class FakeNestedCatalogSession:
    def __init__(self):
        self.headers = {}

    def get(self, *_args, **_kwargs):
        return FakeNestedCatalogResponse()


class FakeIncrementalSession:
    def __init__(self):
        self.headers = {}

    def get(self, url, **_kwargs):
        if "api.github.com" in url:
            return FakeCatalogResponse()
        return FakePlaylistResponse()


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


def test_mytv_discovers_playlists_inside_repository_folders(app):
    with app.app_context():
        sync = GithubTVSync(session=FakeNestedCatalogSession())
        ids = sync.discover()

        assert len(ids) == 1
        playlist = db.session.get(TVPlaylist, ids[0])
        assert playlist.github_path == "dist/cleaned-playlist.m3u"
        assert playlist.source_url.endswith("/dist/cleaned-playlist.m3u")


def test_builtin_source_refresh_does_not_import_every_catalogue_package(app):
    with app.app_context():
        playlist_id, _, _ = seed_tv()
        source = TVSource(
            name="Dragon IPTV catalogue",
            source_type="github_repository",
            locator="mesbahikarim63-commits/hot-dodo",
            protected=True,
        )
        db.session.add(source)
        db.session.flush()
        db.session.get(TVPlaylist, playlist_id).source_id = source.id
        db.session.commit()

        result = TVSourceManager(session=FakeIncrementalSession()).sync(source)

        assert result["catalog_files"] == 2
        assert result["files"] == 1
        assert db.session.query(TVPlaylist).count() == 2
        assert db.session.query(TVPlaylist).filter_by(imported=True).count() == 1


def test_initial_builtin_source_refresh_imports_every_discovered_playlist(app):
    with app.app_context():
        source = TVSource(
            name="Dragon IPTV catalogue",
            source_type="github_repository",
            locator="dragon/tv",
            protected=True,
        )
        db.session.add(source)
        db.session.commit()

        result = TVSourceManager(session=FakeIncrementalSession()).sync(source)

        assert result["catalog_files"] == 2
        assert result["files"] == 2
        assert db.session.query(TVPlaylist).filter_by(imported=True).count() == 2


def test_mytv_incremental_refresh_selects_only_packages_backing_choices(app):
    with app.app_context():
        selected_id, _, _ = seed_tv()
        source = TVSource(
            name="Incremental source",
            source_type="github_repository",
            locator="dragon/tv",
        )
        db.session.add(source)
        db.session.flush()
        db.session.get(TVPlaylist, selected_id).source_id = source.id
        unrelated = TVPlaylist(
            source_id=source.id,
            name="Unrelated package",
            github_path="unrelated.m3u",
            source_url="https://example.test/unrelated.m3u",
            imported=True,
            available=True,
        )
        unrelated_theme = TVTheme(key="sports", name="Sports", enabled=False)
        unrelated_group = TVGroup(name="Sports", theme=unrelated_theme)
        unrelated.groups.append(unrelated_group)
        db.session.add(
            TVChannel(
                playlist=unrelated,
                group=unrelated_group,
                external_key="sport-one",
                preference_key="sport-one",
                name="Sport One",
                stream_url="https://stream.example/sport",
                position=1,
                last_seen_sync="seed",
            )
        )
        db.session.commit()

        assert relevant_playlist_ids([selected_id, unrelated.id]) == [selected_id]
        assert prune_irrelevant_playlist_cache(source.id) == 1
        assert db.session.get(TVPlaylist, selected_id).imported is True
        assert db.session.get(TVPlaylist, unrelated.id).imported is False
        assert db.session.scalar(
            select(TVChannel).where(TVChannel.playlist_id == unrelated.id)
        ) is None


def test_mytv_stale_cache_is_removed_without_deleting_personal_choices(app):
    with app.app_context():
        playlist_id, theme_id, channel_id = seed_tv()
        source = TVSource(
            name="Disposable source",
            source_type="github_repository",
            locator="dragon/tv",
        )
        db.session.add(source)
        db.session.flush()
        playlist = db.session.get(TVPlaylist, playlist_id)
        playlist.source_id = source.id
        playlist.available = False
        theme = db.session.get(TVTheme, theme_id)
        persist_theme_preference(theme)
        channel = db.session.get(TVChannel, channel_id)
        preference_key = channel.preference_key
        db.session.add(
            TVChannelPreference(
                preference_key=preference_key,
                theme_key=theme.key,
                name=channel.name,
                favorite=True,
            )
        )
        db.session.commit()

        assert purge_unavailable_playlists(source.id) == 1
        assert db.session.get(TVPlaylist, playlist_id) is None
        assert db.session.get(TVTheme, theme_id) is None
        assert db.session.get(TVThemePreference, "news") is not None
        assert db.session.get(TVChannelPreference, preference_key).favorite is True


def test_mytv_playback_url_privacy(authenticated_client, app):
    with app.app_context():
        _, _, channel_id = seed_tv()
    headers = csrf_header(authenticated_client)
    authenticated_client.patch(
        f"/my-tv/api/channels/{channel_id}", json={"enabled": True}, headers=headers
    )
    playback = authenticated_client.get(f"/my-tv/api/channels/{channel_id}/playback")
    assert playback.status_code == 200
    payload = playback.get_json()
    assert payload["url"] == f"/my-tv/play/{channel_id}"
    assert payload["startup_timeout_seconds"] >= 20
    assert payload["capabilities"] == {
        "live": True,
        "seek": False,
        "quality_selection": False,
        "audio_track_selection": False,
        "subtitle_selection": False,
    }
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
        preference_key = working.preference_key

    calls: list[str] = []

    def failed_transcode(url: str):
        calls.append(url)
        return Response("upstream unavailable", status=503, content_type="text/plain")

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

    recent = authenticated_client.get("/my-tv/api/channels?state=recent").get_json()
    assert [item["name"] for item in recent["channels"]] == ["News One"]
    assert recent["channels"][0]["last_watched_at"] is not None
    bootstrap = authenticated_client.get("/my-tv/api/bootstrap").get_json()
    assert bootstrap["last_channel"]["name"] == "News One"
    with app.app_context():
        preference = db.session.get(TVChannelPreference, preference_key)
        assert preference.watch_count == 2


def test_mytv_playback_does_not_fall_back_from_a_custom_source(
    authenticated_client, app, monkeypatch
):
    with app.app_context():
        _, theme_id, _ = seed_tv()
        theme = db.session.get(TVTheme, theme_id)
        working = db.session.scalar(
            select(TVChannel).where(TVChannel.name == "News One")
        )
        source = TVSource(
            name="Official replacement",
            source_type="local_file",
            local_path="C:/custom/official.m3u",
            auto_refresh=False,
        )
        playlist = TVPlaylist(
            source=source,
            name="Official replacement package",
            github_path="custom/official.m3u",
            source_url="file:///custom/official.m3u",
            source_sha="custom",
            imported_sha="custom",
            imported=True,
            sync_status="ready",
        )
        group = TVGroup(name="Official News", theme=theme, channel_count=1)
        playlist.groups.append(group)
        official = TVChannel(
            playlist=playlist,
            group=group,
            external_key="official-news-one",
            preference_key=working.preference_key,
            name=working.name,
            stream_url="https://official.example/live.m3u8",
            stream_kind="hls",
            position=1,
            last_seen_sync="custom",
        )
        db.session.add_all([source, playlist, official])
        db.session.commit()
        GithubTVSync.refresh_representatives()
        official_id = official.id

    calls: list[str] = []

    def failed_transcode(url: str):
        calls.append(url)
        return Response("upstream unavailable", status=503, content_type="text/plain")

    def unexpected_fallback(url: str):
        calls.append(url)
        return Response(b"unexpected fallback", content_type="video/mp4")

    monkeypatch.setattr("app.mytv.routes.transcode_stream", failed_transcode)
    monkeypatch.setattr("app.mytv.routes.proxy_file", unexpected_fallback)

    response = authenticated_client.get(f"/my-tv/play/{official_id}")

    assert response.status_code == 502
    assert calls == ["https://official.example/live.m3u8"]


def test_mytv_writes_require_csrf(authenticated_client, app):
    with app.app_context():
        _, theme_id, _ = seed_tv()
    response = authenticated_client.patch(
        f"/my-tv/api/groups/{theme_id}", json={"enabled": False}
    )
    assert response.status_code == 400
