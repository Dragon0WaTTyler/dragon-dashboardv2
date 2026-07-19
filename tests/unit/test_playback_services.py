import pytest

from app.extensions import db
from app.history.models import HistoryEvent
from app.movies.models import Movie
from app.playback.models import PlaybackSource
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


def test_vidsrc_source_requires_a_valid_imdb_id():
    imdb_source = PlaybackService.vidsrc_source(
        movie={"title": "Arrival", "external_ids": {"imdb_id": "tt2543164"}},
        base_url="https://vsembed.ru/embed",
    )

    assert imdb_source["url"] == "https://vsembed.ru/embed/tt2543164"
    assert imdb_source["match"] == "imdb"
    with pytest.raises(ValueError, match="IMDb ID"):
        PlaybackService.vidsrc_source(
            movie={"title": "In the Mood for Love", "external_ids": {}},
            base_url="https://vsembed.ru/embed/",
        )


def test_player_sources_expose_season_pack_metadata(app):
    with app.app_context():
        movie = add_movie()
        db.session.add(
            PlaybackSource(
                movie_id=movie.id,
                kind="magnet",
                label="S01 season pack Jackett magnet",
                locator="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
                metadata_json={"season_pack": True, "season": 1, "release_mode": "season_pack"},
                selected=True,
            )
        )
        db.session.commit()

        sources = PlaybackService.player_sources(movie.id)

        assert sources == [
            {
                "id": sources[0]["id"],
                "label": "S01 season pack Jackett",
                "kind": "magnet",
                "selected": True,
                "season_pack": True,
                "season": 1,
                "episode": None,
                "release_mode": "season_pack",
            }
        ]
