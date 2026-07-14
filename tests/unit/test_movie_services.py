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
