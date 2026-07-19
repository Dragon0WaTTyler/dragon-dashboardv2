from app.extensions import db
from app.movies.models import Movie
from app.playback.models import PlaybackSource
from app.playback.subtitles import SubtitleCandidate
from tests.conftest import csrf_from


def test_playback_routes_are_hidden_when_disabled(authenticated_client, app):
    with app.app_context():
        movie = Movie(title="Hidden Playback", normalized_title="hidden playback")
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id
    response = authenticated_client.get(f"/playback/movie/{movie_id}")
    assert response.status_code == 404
    detail = authenticated_client.get(f"/movies/{movie_id}").get_data(as_text=True)
    assert "Playback sources" not in detail


def test_magnet_route_is_hidden_independently(authenticated_client, app):
    with app.app_context():
        movie = Movie(title="Flags", normalized_title="flags")
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id
    app.config["DRAGON_PLAYBACK_ENABLED"] = True
    app.config["DRAGON_MAGNETS_ENABLED"] = False
    page = authenticated_client.get(f"/playback/movie/{movie_id}")
    assert page.status_code == 200
    assert "disabled by default" in page.get_data(as_text=True)
    response = authenticated_client.post(
        f"/playback/movie/{movie_id}/magnets",
        data={
            "magnet_uri": "magnet:?xt=urn:btih:x",
            "csrf_token": csrf_from(page),
        },
    )
    assert response.status_code == 404


def test_vidsrc_is_click_gated_and_resolved_by_protected_playback_route(authenticated_client, app):
    with app.app_context():
        movie = Movie(
            title="Arrival",
            normalized_title="arrival",
            external_ids={"imdb_id": "tt2543164"},
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config["DRAGON_PLAYBACK_ENABLED"] = True
    app.config["DRAGON_VIDSRC_ENABLED"] = True
    app.config["DRAGON_VIDSRC_EMBED_URL"] = "https://vsembed.ru/embed"

    detail = authenticated_client.get(f"/movies/{movie_id}")
    detail_html = detail.get_data(as_text=True)
    assert "Play with VidSrc" in detail_html
    assert "https://vsembed.ru" not in detail_html
    assert "sandbox=" not in detail_html
    assert "frame-src 'self' https://vsembed.ru" in detail.headers["Content-Security-Policy"]

    response = authenticated_client.get(f"/playback/movie/{movie_id}/vidsrc")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.get_json()["source"] == {
        "provider": "vidsrc",
        "label": "VidSrc",
        "url": "https://vsembed.ru/embed/tt2543164",
        "match": "imdb",
    }

    anonymous = app.test_client().get(f"/playback/movie/{movie_id}/vidsrc")
    assert anonymous.status_code == 302


def test_vidsrc_resolves_and_caches_external_ids(authenticated_client, app):
    class StubIdentityProvider:
        def resolve(self, **values):
            assert values == {
                "title": "Great Teacher Onizuka",
                "year": 1999,
                "media_type": "movie",
                "external_ids": {},
            }
            return {
                "tmdb_id": "43017",
                "tmdb_type": "tv",
                "imdb_id": "tt0315008",
            }

    with app.app_context():
        movie = Movie(
            title="Great Teacher Onizuka",
            normalized_title="great teacher onizuka",
            year=1999,
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config["DRAGON_PLAYBACK_ENABLED"] = True
    app.config["DRAGON_VIDSRC_ENABLED"] = True
    app.config["DRAGON_VIDSRC_EMBED_URL"] = "https://vsembed.ru/embed"
    app.extensions["dragon_tmdb_identity_provider"] = StubIdentityProvider()

    response = authenticated_client.get(f"/playback/movie/{movie_id}/vidsrc")

    assert response.status_code == 200
    assert response.get_json()["source"]["url"] == ("https://vsembed.ru/embed/tt0315008")
    with app.app_context():
        assert db.session.get(Movie, movie_id).external_ids == {
            "tmdb_id": "43017",
            "tmdb_type": "tv",
            "imdb_id": "tt0315008",
        }


def test_vidsrc_v2_redirect_hosts_are_allowed_by_csp(authenticated_client, app):
    app.config["DRAGON_VIDSRC_ENABLED"] = True
    app.config["DRAGON_VIDSRC_EMBED_URL"] = "https://v2.vidsrc.me/embed"

    response = authenticated_client.get("/")

    policy = response.headers["Content-Security-Policy"]
    assert "frame-src 'self' https://v2.vidsrc.me https://vidsrc.me https://vidsrcme.ru" in policy


def test_wyzie_key_enables_subtitle_controls_on_movie_detail(authenticated_client, app):
    with app.app_context():
        movie = Movie(title="Wyzie Ready", normalized_title="wyzie ready")
        db.session.add(movie)
        db.session.flush()
        db.session.add(
            PlaybackSource(
                movie_id=movie.id,
                kind="magnet",
                label="FHD magnet",
                locator="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
            )
        )
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MAGNETS_ENABLED=True,
        DRAGON_SUBTITLES_ENABLED=True,
        DRAGON_SUBTITLE_PROVIDER="wyzie",
        DRAGON_WYZIE_API_KEY="private-wyzie-key",
        DRAGON_SUBDL_API_KEY="",
    )

    detail = authenticated_client.get(f"/movies/{movie_id}")
    detail_html = detail.get_data(as_text=True)

    assert "data-subtitle-status" in detail_html
    assert "from the player controls" in detail_html
    assert "private-wyzie-key" not in detail_html


def test_subtitles_are_private_ranked_and_delivered_as_webvtt(authenticated_client, app):
    class StubSubtitleProvider:
        downloads = 0

        def search(self, movie, *, languages, season=None, episode=None, episode_title=""):
            assert movie["external_ids"] == {"imdb_id": "tt2543164"}
            assert languages == "ar,en"
            assert season is None
            assert episode is None
            assert episode_title == ""
            return [
                SubtitleCandidate(
                    language="ar",
                    language_name="Arabic",
                    label="Arabic release",
                    path="/subtitle/archive123-456.zip",
                    file_format="srt",
                    member_name="arrival.ar.srt",
                    hearing_impaired=False,
                ),
                SubtitleCandidate(
                    language="en",
                    language_name="English",
                    label="English release",
                    path="/subtitle/archive789-012.zip",
                    file_format="srt",
                    member_name="arrival.en.srt",
                    hearing_impaired=False,
                ),
            ]

        def download(self, path, *, file_format, member_name, season=None, episode=None, episode_title=""):
            assert path == "/subtitle/archive123-456.zip"
            assert file_format == "srt"
            assert member_name == "arrival.ar.srt"
            assert season is None
            assert episode is None
            assert episode_title == ""
            self.downloads += 1
            return "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nمرحبا\n".encode()

    provider = StubSubtitleProvider()
    with app.app_context():
        movie = Movie(
            title="Arrival",
            normalized_title="arrival",
            external_ids={"imdb_id": "tt2543164"},
        )
        db.session.add(movie)
        db.session.flush()
        db.session.add(
            PlaybackSource(
                movie_id=movie.id,
                kind="magnet",
                label="FHD magnet",
                locator="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
            )
        )
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MAGNETS_ENABLED=True,
        DRAGON_SUBTITLES_ENABLED=True,
        DRAGON_SUBDL_API_KEY="private-key",
        DRAGON_SUBTITLE_LANGUAGES="ar,en",
    )
    app.extensions["dragon_subtitle_provider"] = provider

    detail = authenticated_client.get(f"/movies/{movie_id}")
    detail_html = detail.get_data(as_text=True)
    assert "data-subtitle-status" in detail_html
    assert "from the player controls" in detail_html
    assert "data-subtitle-select" not in detail_html
    assert "private-key" not in detail_html
    assert "dl.subdl.com" not in detail_html

    options = authenticated_client.get(f"/playback/movie/{movie_id}/subtitles")
    assert options.status_code == 200
    items = options.get_json()["items"]
    assert [item["language"] for item in items] == ["ar", "en"]
    assert all("dl.subdl.com" not in item["track_url"] for item in items)

    track_url = items[0]["track_url"]
    track = authenticated_client.get(track_url)
    assert track.status_code == 200
    assert track.mimetype == "text/vtt"
    assert "مرحبا" in track.get_data(as_text=True)
    assert track.headers["Cache-Control"] == "private, max-age=3600"
    authenticated_client.get(track_url)
    assert provider.downloads == 1

    assert authenticated_client.get(f"{track_url}tampered").status_code == 404
    assert app.test_client().get(track_url).status_code == 302


def test_tv_subtitles_follow_selected_season_and_episode(authenticated_client, app):
    class StubSubtitleProvider:
        def search(self, movie, *, languages, season=None, episode=None, episode_title=""):
            assert movie["external_ids"] == {"tmdb_id": "1399", "tmdb_type": "tv"}
            assert languages == "ar,en"
            assert season == 1
            assert episode == 2
            assert episode_title == "46 Long"
            return [
                SubtitleCandidate(
                    language="ar",
                    language_name="Arabic",
                    label="The Sopranos - Season 1",
                    path="/subtitle/archive123-456.zip",
                    file_format="srt",
                    member_name="sopranos.s01e02.ar.srt",
                    hearing_impaired=False,
                    season=1,
                    episode=2,
                    episode_title="46 Long",
                )
            ]

        def download(self, path, *, file_format, member_name, season=None, episode=None, episode_title=""):
            assert season == 1
            assert episode == 2
            assert episode_title == "46 Long"
            return "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nمرحبا\n".encode()

    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            external_ids={"tmdb_id": "1399", "tmdb_type": "tv"},
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MAGNETS_ENABLED=True,
        DRAGON_SUBTITLES_ENABLED=True,
        DRAGON_SUBDL_API_KEY="private-key",
        DRAGON_SUBTITLE_LANGUAGES="ar,en",
    )
    app.extensions["dragon_subtitle_provider"] = StubSubtitleProvider()

    response = authenticated_client.get(
        f"/playback/movie/{movie_id}/subtitles?season=1&episode=2&episode_title=46+Long"
    )

    assert response.status_code == 200
    items = response.get_json()["items"]
    assert len(items) == 1
    assert items[0]["label"] == "The Sopranos - Season 1"
    track = authenticated_client.get(items[0]["track_url"])
    assert track.status_code == 200


def test_local_magnet_player_is_click_gated_and_keeps_locator_server_side(
    authenticated_client, app
):
    class StubRuntime:
        def start(self, **values):
            assert values["movie_id"] == movie_id
            assert values["source_id"] == source_id
            assert values["magnet"].startswith("magnet:?")
            assert values["torrent_url"] == "https://yts.bz/example.torrent"
            assert values["user_id"]
            assert values["origin"] == "http://localhost"
            assert values["season"] == 1
            assert values["episode"] == 1
            return {
                "id": "play_test",
                "state": "ready",
                "message": "Direct stream ready",
                "file_name": "movie.mp4",
                "stream_url": "http://127.0.0.1:54321/dragon-stream/secret/hash/movie.mp4",
                "stream_kind": "direct",
                "buffer_percent": 50,
                "file_progress": 0.1,
                "downloaded_bytes": 100,
                "peers": 2,
                "download_speed": 1024,
                "cache_hit": True,
                "startup_timings": {"metadata_ms": 10},
                "complete": False,
            }

    locator = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
    with app.app_context():
        movie = Movie(title="Local Player", normalized_title="local player")
        db.session.add(movie)
        db.session.flush()
        source = PlaybackSource(
            movie_id=movie.id,
            kind="magnet",
            label="FHD magnet",
            locator=locator,
            metadata_json={"season": 1, "episode": 1, "season_pack": True},
        )
        db.session.add(source)
        db.session.add(
            PlaybackSource(
                movie_id=movie.id,
                kind="torrent",
                label="FHD torrent",
                locator="https://yts.bz/example.torrent",
            )
        )
        db.session.commit()
        movie_id = movie.id
        source_id = source.id

    app.config["DRAGON_PLAYBACK_ENABLED"] = True
    app.config["DRAGON_MAGNETS_ENABLED"] = True
    app.extensions["dragon_magnet_playback_manager"] = StubRuntime()

    detail = authenticated_client.get(f"/movies/{movie_id}")
    html = detail.get_data(as_text=True)
    assert "Local · FHD" in html
    assert locator not in html
    assert "http://127.0.0.1:" not in html
    assert "media-src 'self' http://127.0.0.1:*" in detail.headers[
        "Content-Security-Policy"
    ]

    response = authenticated_client.post(
        f"/playback/movie/{movie_id}/local",
        json={"source_id": source_id},
        headers={"X-CSRFToken": csrf_from(detail)},
    )
    assert response.status_code == 202
    payload = response.get_json()
    assert payload["session"]["id"] == "play_test"
    assert payload["stream_url"].startswith("http://127.0.0.1:54321/dragon-stream/")
    assert payload["session"]["stream_kind"] == "direct"
    assert payload["transcode_url"].endswith("/playback/runtime/play_test/transcode")
    assert authenticated_client.get("/playback/runtime/play_test/stream").status_code == 404


def test_season_pack_player_exposes_episode_controls_and_payload_overrides(
    authenticated_client, app
):
    class StubRuntime:
        def start(self, **values):
            assert values["season"] == 1
            assert values["episode"] == 5
            return {
                "id": "play_pack",
                "state": "ready",
                "message": "Direct stream ready",
                "file_name": "episode.mp4",
                "stream_url": "http://127.0.0.1:54321/dragon-stream/secret/hash/episode.mp4",
                "stream_kind": "direct",
                "buffer_percent": 50,
                "file_progress": 0.1,
                "downloaded_bytes": 100,
                "peers": 2,
                "download_speed": 1024,
                "cache_hit": True,
                "startup_timings": {"metadata_ms": 10},
                "complete": False,
            }

    with app.app_context():
        movie = Movie(
            title="Pack Show",
            normalized_title="pack show",
            media_type="tv",
            external_ids={"tmdb_id": "1399", "tmdb_type": "tv"},
        )
        db.session.add(movie)
        db.session.flush()
        source = PlaybackSource(
            movie_id=movie.id,
            kind="magnet",
            label="S01 season pack Jackett magnet",
            locator="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
            metadata_json={"season_pack": True, "season": 1, "release_mode": "season_pack"},
            selected=True,
        )
        db.session.add(source)
        db.session.commit()
        movie_id = movie.id
        source_id = source.id

    app.config["DRAGON_PLAYBACK_ENABLED"] = True
    app.config["DRAGON_MAGNETS_ENABLED"] = True
    app.extensions["dragon_magnet_playback_manager"] = StubRuntime()

    detail = authenticated_client.get(f"/movies/{movie_id}")
    html = detail.get_data(as_text=True)
    assert 'data-source-season-pack="true"' in html
    assert 'data-source-season="1"' in html
    assert "data-player-pack-browser" in html

    response = authenticated_client.post(
        f"/playback/movie/{movie_id}/local",
        json={"source_id": source_id, "season": 1, "episode": 5},
        headers={"X-CSRFToken": csrf_from(detail)},
    )

    assert response.status_code == 202
    assert response.get_json()["session"]["id"] == "play_pack"


def test_local_transcode_route_uses_private_loopback_stream_safely(
    authenticated_client, app, monkeypatch
):
    class StubRuntime:
        def status(self, session_id: str, *, user_id: str):
            assert session_id == "play_test"
            assert user_id
            return {
                "id": session_id,
                "state": "ready",
                "message": "Transcode required",
                "file_name": "episode.mkv",
                "stream_url": "http://127.0.0.1:54321/dragon-stream/secret/hash/episode.mkv",
                "stream_kind": "transcode",
                "buffer_percent": 25,
                "file_progress": 0.05,
                "downloaded_bytes": 100,
                "total_bytes": 1000,
                "peers": 1,
                "download_speed": 512,
                "cache_hit": False,
                "startup_timings": {},
                "complete": False,
            }

    called = {}

    def fake_transcode(
        url: str,
        *,
        allow_private: bool = False,
        input_headers=None,
        start_seconds=None,
    ):
        called["url"] = url
        called["allow_private"] = allow_private
        called["input_headers"] = dict(input_headers or {})
        called["start_seconds"] = start_seconds
        from flask import Response

        return Response(b"mp4-bytes", content_type="video/mp4")

    app.config["DRAGON_PLAYBACK_ENABLED"] = True
    app.config["DRAGON_MAGNETS_ENABLED"] = True
    app.extensions["dragon_magnet_playback_manager"] = StubRuntime()
    monkeypatch.setattr("app.playback.routes.transcode_stream", fake_transcode)

    response = authenticated_client.get("/playback/runtime/play_test/transcode")
    assert response.status_code == 200
    assert response.mimetype == "video/mp4"
    assert called["url"].endswith("/dragon-stream/secret/hash/episode.mkv")
    assert called["allow_private"] is True
    assert called["input_headers"]["Origin"] == "http://localhost"
    assert called["start_seconds"] is None


def test_local_transcode_route_accepts_start_offset(
    authenticated_client, app, monkeypatch
):
    class StubRuntime:
        def status(self, session_id: str, *, user_id: str):
            assert session_id == "play_test"
            assert user_id
            return {
                "id": session_id,
                "state": "ready",
                "message": "Transcode required",
                "file_name": "episode.mkv",
                "stream_url": "http://127.0.0.1:54321/dragon-stream/secret/hash/episode.mkv",
                "stream_kind": "transcode",
                "buffer_percent": 25,
                "file_progress": 0.05,
                "downloaded_bytes": 100,
                "total_bytes": 1000,
                "peers": 1,
                "download_speed": 512,
                "cache_hit": False,
                "startup_timings": {},
                "complete": False,
            }

    called = {}

    def fake_transcode(
        url: str,
        *,
        allow_private: bool = False,
        input_headers=None,
        start_seconds=None,
    ):
        called["url"] = url
        called["allow_private"] = allow_private
        called["input_headers"] = dict(input_headers or {})
        called["start_seconds"] = start_seconds
        from flask import Response

        return Response(b"mp4-bytes", content_type="video/mp4")

    app.config["DRAGON_PLAYBACK_ENABLED"] = True
    app.config["DRAGON_MAGNETS_ENABLED"] = True
    app.extensions["dragon_magnet_playback_manager"] = StubRuntime()
    monkeypatch.setattr("app.playback.routes.transcode_stream", fake_transcode)

    response = authenticated_client.get("/playback/runtime/play_test/transcode?start=42.5")
    assert response.status_code == 200
    assert called["start_seconds"] == 42.5
