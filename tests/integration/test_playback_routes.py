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
