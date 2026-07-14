import pytest

from app.extensions import db
from app.history.models import HistoryEvent
from app.movies.models import Movie
from app.playback.services import PlaybackService


def add_movie() -> Movie:
    movie = Movie(title="Playback Film", normalized_title="playback film")
    db.session.add(movie)
    db.session.commit()
    return movie


def test_local_source_requires_existing_absolute_file(app, tmp_path):
    with app.app_context():
        movie = add_movie()
        media = tmp_path / "film.mp4"
        media.write_bytes(b"not-real-media")
        source = PlaybackService.add_local_file(movie_id=movie.id, path_value=str(media))
        assert source.kind == "local_file"
        assert source.label == "film.mp4"
        assert source.locator == str(media.resolve())
        assert db.session.scalar(db.select(HistoryEvent)).event_type == "playback_source_added"

        with pytest.raises(ValueError):
            PlaybackService.add_local_file(movie_id=movie.id, path_value="relative.mp4")


def test_magnet_is_normalized_without_launching_a_client(app):
    with app.app_context():
        movie = add_movie()
        candidate = PlaybackService.add_magnet(
            movie_id=movie.id,
            magnet_uri=(
                "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
                "&dn=Reviewed%20Source"
            ),
        )
        assert candidate.info_hash == "0123456789abcdef0123456789abcdef01234567"
        assert candidate.display_name == "Reviewed Source"
        assert candidate.approved is False
        PlaybackService.approve_magnet(candidate)
        assert candidate.review_state == "approved"

        with pytest.raises(ValueError):
            PlaybackService.add_magnet(movie_id=movie.id, magnet_uri="https://example.test")
