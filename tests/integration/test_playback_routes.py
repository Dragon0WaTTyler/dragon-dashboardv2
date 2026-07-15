from app.extensions import db
from app.movies.models import Movie
from app.playback.models import PlaybackSource
from app.playback.runtime import StreamRange
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


def test_vidsrc_is_click_gated_and_resolved_by_protected_playback_route(
    authenticated_client, app
):
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
    assert "frame-src 'self' https://vsembed.ru" in detail.headers[
        "Content-Security-Policy"
    ]

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
    assert response.get_json()["source"]["url"] == (
        "https://vsembed.ru/embed/tt0315008"
    )
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
    assert (
        "frame-src 'self' https://v2.vidsrc.me https://vidsrc.me https://vidsrcme.ru"
        in policy
    )


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
            return {
                "id": "play_test",
                "state": "preparing",
                "message": "Reading torrent metadata…",
                "file_name": "",
                "buffer_percent": 0,
                "peers": 0,
                "download_speed": 0,
                "complete": False,
            }

        def open_range(self, session_id, **values):
            assert session_id == "play_test"
            assert values["range_header"] == "bytes=0-5"
            return StreamRange(start=0, end=5, total=12, mime_type="video/mp4")

        def read_chunk(self, session_id, **values):
            assert session_id == "play_test"
            assert (values["start"], values["end"]) == (0, 5)
            return b"dragon"

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

    response = authenticated_client.post(
        f"/playback/movie/{movie_id}/local",
        json={"source_id": source_id},
        headers={"X-CSRFToken": csrf_from(detail)},
    )
    assert response.status_code == 202
    payload = response.get_json()
    assert payload["session"]["id"] == "play_test"
    assert payload["stream_url"].endswith("/playback/runtime/play_test/stream")

    stream = authenticated_client.get(
        payload["stream_url"], headers={"Range": "bytes=0-5"}, buffered=False
    )
    assert stream.status_code == 206
    assert stream.headers["Content-Range"] == "bytes 0-5/12"
    assert b"".join(stream.response) == b"dragon"
