from datetime import UTC, datetime, timedelta

import pytest

from app.extensions import db
from app.movies.models import Movie
from app.movies.services import MovieService, ProgressConflictError, parse_movie_filters


def _movie() -> Movie:
    return Movie(title="Arrival", normalized_title="arrival", status="watching")


def test_movie_filter_validation():
    filters, errors = parse_movie_filters(
        {"status": "watching", "sort": "score_desc", "year_min": "2000", "score_max": "5"}
    )
    assert errors == {}
    assert filters["year_min"] == 2000
    assert filters["score_max"] == 5

    _, errors = parse_movie_filters(
        {"status": "invalid", "sort": "random", "view": "cinema", "year_min": "x"}
    )
    assert set(errors) == {"status", "sort", "view", "year_min"}


def test_progress_is_clamped_and_rejects_stale_updates(app):
    with app.app_context():
        movie = _movie()
        db.session.add(movie)
        db.session.commit()
        timestamp = datetime.now(UTC)
        progress = MovieService.save_progress(
            movie,
            current_seconds=150,
            duration_seconds=100,
            completed=False,
            client_updated_at=timestamp,
        )
        assert progress.current_seconds == 100

        with pytest.raises(ProgressConflictError):
            MovieService.save_progress(
                movie,
                current_seconds=10,
                duration_seconds=100,
                completed=False,
                client_updated_at=timestamp - timedelta(minutes=1),
            )


def test_status_and_score_validation(app):
    with app.app_context():
        movie = _movie()
        db.session.add(movie)
        db.session.commit()
        MovieService.set_status(movie, "watched")
        MovieService.set_score(movie, 4.5)
        assert movie.status == "watched"
        assert movie.personal_score == 4.5
        with pytest.raises(ValueError):
            MovieService.set_score(movie, 7)


def test_recommendation_pool_uses_profile_and_excludes_watched(app):
    with app.app_context():
        liked = Movie(
            title="In the Mood for Love",
            normalized_title="in the mood for love",
            status="finished",
            personal_score=8,
            category="movie",
            source="My library",
            directors=[{"name": "Wong Kar-wai"}],
            genres=[{"name": "Drama"}],
        )
        candidate = Movie(
            title="Chungking Express",
            normalized_title="chungking express",
            year=1994,
            runtime_minutes=102,
            status="want_to_watch",
            category="movie",
            source="My library",
            overview="Two stories of love and chance in Hong Kong.",
            poster_url="https://example.test/chungking.jpg",
            directors=[{"name": "Wong Kar-wai"}],
            genres=[{"name": "Drama"}],
        )
        watched = Movie(
            title="Fallen Angels",
            normalized_title="fallen angels",
            status="watched",
            category="movie",
            source="My library",
        )
        db.session.add_all([liked, candidate, watched])
        db.session.commit()

        result = MovieService.recommendation_pool()

        assert [item["id"] for item in result["items"]] == [candidate.id]
        assert result["items"][0]["tier"] == 0
        assert result["items"][0]["recommendation_explanation"]["confidence"] == "high"
        assert "Same director" in result["items"][0]["recommendation_reason"]
        assert result["summary"]["excluded_watched"] == 2
