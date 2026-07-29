from app.extensions import db
from app.movies.models import Movie
from tests.conftest import csrf_from


def add_movie(app) -> str:
    with app.app_context():
        movie = Movie(
            title="Perfect Days",
            normalized_title="perfect days",
            year=2023,
            runtime_minutes=124,
            status="want_to_watch",
            category="movie",
            source="My library",
            overview="A Tokyo cleaner finds beauty in his precise daily rituals.",
            poster_url="https://example.test/perfect-days.jpg",
            genres=[{"name": "Drama"}],
            directors=[{"name": "Wim Wenders"}],
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


def test_movie_recommendation_contract(authenticated_client, app):
    movie_id = add_movie(app)
    response = authenticated_client.get("/api/v1/movies/recommendations")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["api_version"] == "v1"
    assert payload["item"]["summary"]["eligible"] == 1
    assert payload["item"]["items"][0]["id"] == movie_id
    assert payload["item"]["items"][0]["recommendation_reason"]


def test_live_home_rotation_contract(authenticated_client, app):
    add_movie(app)
    response = authenticated_client.get("/api/v1/home/live")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["item"]["recommended_movie"]["id"]
    assert payload["item"]["rotation"]["movie_interval_seconds"] == 3600
    assert payload["item"]["rotation"]["youtube_interval_seconds"] == 300


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


def test_tv_playback_progress_is_scoped_by_episode(authenticated_client, app):
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

    token = csrf_from(authenticated_client.get(f"/movies/{movie_id}"))
    first = {
        "season": 1,
        "episode": 5,
        "current_seconds": 60,
        "duration_seconds": 120,
        "completed": False,
        "client_updated_at": "2026-07-14T10:00:00Z",
    }
    second = {
        "season": 1,
        "episode": 6,
        "current_seconds": 20,
        "duration_seconds": 100,
        "completed": False,
        "client_updated_at": "2026-07-14T10:01:00Z",
    }
    for payload in (first, second):
        response = authenticated_client.put(
            f"/api/v1/playback-progress/movie/{movie_id}",
            json=payload,
            headers={"X-CSRFToken": token},
        )
        assert response.status_code == 200

    episode_five = authenticated_client.get(
        f"/api/v1/playback-progress/movie/{movie_id}?season=1&episode=5"
    )
    episode_six = authenticated_client.get(
        f"/api/v1/playback-progress/movie/{movie_id}?season=1&episode=6"
    )
    assert episode_five.get_json()["item"]["progress"]["percent"] == 50
    assert episode_six.get_json()["item"]["progress"]["percent"] == 20


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
