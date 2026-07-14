from app.extensions import db
from app.movies.models import Movie
from tests.conftest import csrf_from


def add_movie(app, **overrides) -> str:
    values = {
        "title": "Arrival",
        "normalized_title": "arrival",
        "year": 2016,
        "status": "watching",
        "personal_score": 4.5,
        "genres": [{"name": "Science Fiction"}],
    }
    values.update(overrides)
    with app.app_context():
        movie = Movie(**values)
        db.session.add(movie)
        db.session.commit()
        return movie.id


def test_movie_pages_are_protected_and_render_local_data(authenticated_client, app):
    movie_id = add_movie(app)
    assert app.test_client().get("/movies").status_code == 302

    listing = authenticated_client.get("/movies?q=arrival&genre=Science+Fiction")
    detail = authenticated_client.get(f"/movies/{movie_id}")
    assert listing.status_code == 200
    assert "Arrival" in listing.get_data(as_text=True)
    assert detail.status_code == 200
    assert "Science Fiction" in detail.get_data(as_text=True)


def test_movie_status_mutation_requires_csrf(authenticated_client, app):
    movie_id = add_movie(app)
    assert authenticated_client.post(
        f"/movies/{movie_id}/status", data={"status": "watched"}
    ).status_code == 400
    page = authenticated_client.get(f"/movies/{movie_id}")
    response = authenticated_client.post(
        f"/movies/{movie_id}/status",
        data={"status": "watched", "csrf_token": csrf_from(page)},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Movie, movie_id).status == "watched"
