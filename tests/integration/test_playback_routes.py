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


def test_subtitles_are_private_ranked_and_delivered_as_webvtt(authenticated_client, app):
    class StubSubtitleProvider:
        downloads = 0

        def search(self, movie, *, languages):
            assert movie["external_ids"] == {"imdb_id": "tt2543164"}
            assert languages == "ar,en"
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

        def download(self, path, *, file_format, member_name):
            assert path == "/subtitle/archive123-456.zip"
            assert file_format == "srt"
            assert member_name == "arrival.ar.srt"
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
            return {
                "id": "play_test",
                "state": "ready",
                "message": "Direct stream ready",
                "file_name": "movie.mp4",
                "stream_url": "http://127.0.0.1:54321/dragon-stream/secret/hash/movie.mp4",
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
    assert authenticated_client.get("/playback/runtime/play_test/stream").status_code == 404
