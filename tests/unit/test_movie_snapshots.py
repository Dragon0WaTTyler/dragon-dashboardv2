import json

import pytest

from app.auth.models import User
from app.extensions import db
from app.movies.models import (
    Movie,
    MovieCustomList,
    MovieCustomListItem,
    MovieLibraryEntry,
    MovieProgress,
)
from app.movies.snapshots import (
    MoviesSnapshotValidationError,
    apply_movies_snapshot,
    export_movies_snapshot,
    preview_movies_snapshot,
    validate_movies_snapshot,
)


def _seed_movies_state(app):
    with app.app_context():
        owner = User(username="snapshot-owner", password_hash="unused")
        movie = Movie(
            title="Snapshot Film",
            normalized_title="snapshot film",
            media_type="movie",
            external_ids={"tmdb_id": "100", "imdb_id": "tt0100"},
            metadata_state={"api_key": "must-not-export"},
        )
        show = Movie(
            title="Snapshot Show",
            normalized_title="snapshot show",
            media_type="tv",
            external_ids={"tmdb_id": "200"},
        )
        db.session.add_all([owner, movie, show])
        db.session.flush()
        db.session.add_all(
            [
                MovieLibraryEntry(
                    media_key=movie.media_key,
                    movie_id=movie.id,
                    lifecycle_status="watching",
                    is_favorite=True,
                    personal_rating=4.5,
                    personal_label="great movie",
                ),
                MovieLibraryEntry(
                    media_key=show.media_key,
                    movie_id=show.id,
                    lifecycle_status="want_to_watch",
                ),
                MovieProgress(
                    movie_id=movie.id,
                    current_seconds=95,
                    duration_seconds=100,
                    completed=True,
                ),
                MovieProgress(
                    movie_id=show.id,
                    season=1,
                    episode=2,
                    current_seconds=420,
                    duration_seconds=1200,
                    completed=False,
                ),
            ]
        )
        custom_list = MovieCustomList(
            id="mls_snapshot_fixture",
            owner_user_id=owner.id,
            title="Weekend picks",
            description="Portable list",
        )
        db.session.add(custom_list)
        db.session.flush()
        db.session.add(
            MovieCustomListItem(
                custom_list_id=custom_list.id,
                movie_id=show.id,
                position=3,
            )
        )
        db.session.commit()
        return owner.id


def test_movies_snapshot_round_trip_preserves_personal_state_without_runtime_data(app):
    owner_id = _seed_movies_state(app)
    with app.app_context():
        from app.admin.control_center import preference_store

        preference_store().set_movie_preferences(
            {
                "autoplay_next": False,
                "automatic_resume": True,
                "default_subtitle_language": "fr",
                "preferred_source": "vidsrc",
                "preferred_region": "MA",
                "reduced_effects": True,
                "ambient_level": "normal",
            }
        )
        snapshot = export_movies_snapshot(owner_user_id=owner_id)
        serialized = json.dumps(snapshot)
        assert snapshot["schema_version"] == 1
        assert "must-not-export" not in serialized
        assert "metadata_state" not in serialized

        db.session.execute(db.delete(MovieCustomListItem))
        db.session.execute(db.delete(MovieCustomList))
        db.session.execute(db.delete(MovieProgress))
        db.session.execute(db.delete(MovieLibraryEntry))
        db.session.execute(db.delete(Movie))
        db.session.commit()
        preference_store().set_movie_preferences(
            {
                "autoplay_next": True,
                "automatic_resume": False,
                "default_subtitle_language": "",
                "preferred_source": "",
                "preferred_region": "US",
                "reduced_effects": False,
                "ambient_level": "subtle",
            }
        )

        preview = preview_movies_snapshot(snapshot, owner_user_id=owner_id)
        result = apply_movies_snapshot(snapshot, owner_user_id=owner_id)

        assert preview["media"] == {"create": 2, "keep": 0}
        assert result["media"]["created"] == 2
        entries = list(db.session.scalars(db.select(MovieLibraryEntry)))
        assert {
            (entry.lifecycle_status, entry.is_favorite, entry.personal_rating) for entry in entries
        } == {
            ("watching", True, 4.5),
            ("want_to_watch", False, None),
        }
        episode = db.session.scalar(
            db.select(MovieProgress).where(MovieProgress.season == 1, MovieProgress.episode == 2)
        )
        assert (episode.current_seconds, episode.duration_seconds, episode.completed) == (
            420,
            1200,
            False,
        )
        restored_list = db.session.get(MovieCustomList, "mls_snapshot_fixture")
        assert [(item.position, item.movie.media_key) for item in restored_list.items] == [
            (3, "tv:200")
        ]
        assert preference_store().read()["sections"]["movies"]["movie_preferences"] == snapshot[
            "preferences"
        ]

        repeat = apply_movies_snapshot(snapshot, owner_user_id=owner_id)
        assert repeat["media"]["created"] == 0
        assert repeat["custom_lists"]["memberships_created"] == 0
        assert db.session.scalar(db.select(db.func.count()).select_from(MovieCustomListItem)) == 1


def test_movies_snapshot_rejects_invalid_schema_without_mutating_movies(app):
    owner_id = _seed_movies_state(app)
    with app.app_context():
        snapshot = export_movies_snapshot(owner_user_id=owner_id)
        snapshot["schema_version"] = 99
        before = db.session.scalar(db.select(db.func.count()).select_from(Movie))

        with pytest.raises(MoviesSnapshotValidationError, match="unsupported"):
            apply_movies_snapshot(snapshot, owner_user_id=owner_id)

        assert db.session.scalar(db.select(db.func.count()).select_from(Movie)) == before


def test_movies_snapshot_accepts_v0_missing_optional_sections(app):
    owner_id = _seed_movies_state(app)
    with app.app_context():
        snapshot = export_movies_snapshot(owner_user_id=owner_id)
        snapshot["schema_version"] = 0
        snapshot.pop("progress")
        snapshot.pop("custom_lists")
        snapshot.pop("preferences")

        normalized = validate_movies_snapshot(snapshot)

    assert normalized["schema_version"] == 1
    assert normalized["progress"] == []
    assert normalized["custom_lists"] == []
    assert normalized["preferences"]["preferred_region"] == "US"
