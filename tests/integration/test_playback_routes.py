from app.extensions import db
from app.movies.models import Movie
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
