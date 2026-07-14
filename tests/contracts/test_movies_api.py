from app.extensions import db
from app.movies.models import Movie
from tests.conftest import csrf_from


def add_movie(app) -> str:
    with app.app_context():
        movie = Movie(
            title="Perfect Days",
            normalized_title="perfect days",
            year=2023,
            status="want_to_watch",
        )
        db.session.add(movie)
        db.session.commit()
        return movie.id


def test_movie_collection_contract(authenticated_client, app):
    movie_id = add_movie(app)
    response = authenticated_client.get("/api/v1/movies?limit=10&offset=0")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["api_version"] == "v1"
    assert payload["count"] == 1
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == movie_id
    assert payload["has_more"] is False

    home = authenticated_client.get("/api/v1/home").get_json()["item"]
    assert home["continue_watching"] == []
    assert isinstance(home["freshness_warnings"], list)


def test_playback_progress_contract_and_conflict(authenticated_client, app):
    movie_id = add_movie(app)
    page = authenticated_client.get(f"/movies/{movie_id}")
    token = csrf_from(page)
    payload = {
        "current_seconds": 60,
        "duration_seconds": 120,
        "completed": False,
        "client_updated_at": "2026-07-14T10:00:00Z",
    }
    response = authenticated_client.put(
        f"/api/v1/playback-progress/movie/{movie_id}",
        json=payload,
        headers={"X-CSRFToken": token},
    )
    assert response.status_code == 200
    assert response.get_json()["item"]["progress"]["percent"] == 50

    payload["client_updated_at"] = "2026-07-14T09:00:00Z"
    conflict = authenticated_client.put(
        f"/api/v1/playback-progress/movie/{movie_id}",
        json=payload,
        headers={"X-CSRFToken": token},
    )
    assert conflict.status_code == 409
    assert conflict.get_json()["error"]["code"] == "progress_conflict"


def test_playback_progress_rejects_bad_json(authenticated_client, app):
    movie_id = add_movie(app)
    token = csrf_from(authenticated_client.get(f"/movies/{movie_id}"))
    response = authenticated_client.put(
        f"/api/v1/playback-progress/movie/{movie_id}",
        json={"current_seconds": -1, "duration_seconds": "bad"},
        headers={"X-CSRFToken": token},
    )
    assert response.status_code == 422
    assert set(response.get_json()["error"]["fields"]) >= {
        "current_seconds",
        "duration_seconds",
    }
