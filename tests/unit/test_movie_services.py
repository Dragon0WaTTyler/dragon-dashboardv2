from datetime import UTC, datetime, timedelta

import pytest

from app.extensions import db
from app.movies.models import Movie
from app.movies.services import (
    MovieService,
    ProgressConflictError,
    parse_movie_filters,
    tv_show_workspace,
    tv_season_workspace,
)
from app.playback.models import PlaybackSource


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


def test_episode_progress_is_saved_independently(app):
    with app.app_context():
        movie = Movie(title="The Sopranos", normalized_title="the sopranos", media_type="tv")
        db.session.add(movie)
        db.session.commit()

        episode_five = MovieService.save_progress(
            movie,
            season=1,
            episode=5,
            current_seconds=300,
            duration_seconds=600,
            completed=False,
        )
        episode_six = MovieService.save_progress(
            movie,
            season=1,
            episode=6,
            current_seconds=60,
            duration_seconds=600,
            completed=False,
        )

        assert episode_five.id != episode_six.id
        assert MovieService.get_progress(movie, season=1, episode=5).current_seconds == 300
        assert MovieService.get_progress(movie, season=1, episode=6).current_seconds == 60


def test_status_and_score_validation(app):
    with app.app_context():
        movie = _movie()
        db.session.add(movie)
        db.session.commit()
        MovieService.set_status(movie, "watched")
        MovieService.set_score(movie, 4.5, label="close to god mode")
        assert movie.status == "watched"
        assert movie.personal_score == 4.5
        assert movie.metadata_state["personal_score_label"] == "close to god mode"
        MovieService.set_score(movie, None)
        assert "personal_score_label" not in movie.metadata_state
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


def test_tv_season_workspace_handles_episodes_without_progress(app):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            metadata_state={
                "tv_total_seasons": 1,
                "tv_total_episodes": 2,
                "tv_seasons": [
                    {"season_number": 1, "name": "Season 1", "episode_count": 2, "poster_url": ""}
                ],
                "tv_episodes": {
                    "1": [
                        {"season_number": 1, "episode_number": 1, "name": "Pilot"},
                        {"season_number": 1, "episode_number": 2, "name": "46 Long"},
                    ]
                },
            },
        )
        db.session.add(movie)
        db.session.commit()

        workspace = tv_season_workspace(movie, season_number=1)

        assert workspace["selected_episode"]["episode_number"] == 1
        assert workspace["season"]["watched_episode_count"] == 0
        assert workspace["season"]["completion_percent"] == 0


def test_tv_season_workspace_recognizes_legacy_season_pack_sources(app):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            metadata_state={
                "tv_total_seasons": 1,
                "tv_total_episodes": 2,
                "tv_seasons": [
                    {"season_number": 1, "name": "Season 1", "episode_count": 2, "poster_url": ""}
                ],
                "tv_episodes": {
                    "1": [
                        {"season_number": 1, "episode_number": 1, "name": "Pilot"},
                        {"season_number": 1, "episode_number": 2, "name": "46 Long"},
                    ]
                },
            },
        )
        db.session.add(movie)
        db.session.flush()
        db.session.add_all(
            [
                PlaybackSource(
                    movie_id=movie.id,
                    kind="magnet",
                    label="S01 season pack Jackett magnet",
                    locator="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
                    source_role="",
                    metadata_json={
                        "season_pack": True,
                        "season": 1,
                        "episode": 1,
                        "release_mode": "season_pack",
                    },
                    selected=True,
                ),
                PlaybackSource(
                    movie_id=movie.id,
                    kind="magnet",
                    label="S01 season pack Jackett magnet",
                    locator="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
                    season=1,
                    episode=None,
                    source_role="season_pack_fallback",
                    metadata_json={
                        "season_pack": True,
                        "season": 1,
                        "release_mode": "season_pack",
                    },
                    selected=True,
                ),
            ]
        )
        db.session.commit()

        workspace = tv_season_workspace(movie, season_number=1, selected_episode=1)

        assert workspace["selected_episode"]["has_fallback_source"] is True
        assert workspace["selected_episode"]["has_local_source"] is True
        assert len(workspace["player_sources"]) == 1
        assert workspace["player_sources"][0]["season_pack"] is True
        assert workspace["player_sources"][0]["source_role"] == "season_pack_fallback"


def test_tv_show_workspace_prefers_partial_episode_for_resume(app):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            metadata_state={
                "tv_total_seasons": 1,
                "tv_total_episodes": 2,
                "tv_seasons": [
                    {"season_number": 1, "name": "Season 1", "episode_count": 2, "poster_url": ""}
                ],
                "tv_episodes": {
                    "1": [
                        {"season_number": 1, "episode_number": 1, "name": "Pilot"},
                        {"season_number": 1, "episode_number": 2, "name": "46 Long"},
                    ]
                },
            },
        )
        db.session.add(movie)
        db.session.commit()

        MovieService.save_progress(
            movie,
            season=1,
            episode=2,
            current_seconds=180,
            duration_seconds=1200,
            completed=False,
        )

        workspace = tv_show_workspace(movie)

        assert workspace["resume_target"]["mode"] == "resume"
        assert workspace["resume_target"]["season"] == 1
        assert workspace["resume_target"]["episode"] == 2
        assert workspace["resume_target"]["progress"]["percent"] == 15


def test_tv_show_workspace_falls_back_to_next_episode_when_no_partial_resume_exists(app):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            metadata_state={
                "tv_total_seasons": 1,
                "tv_total_episodes": 2,
                "tv_seasons": [
                    {"season_number": 1, "name": "Season 1", "episode_count": 2, "poster_url": ""}
                ],
                "tv_episodes": {
                    "1": [
                        {"season_number": 1, "episode_number": 1, "name": "Pilot"},
                        {"season_number": 1, "episode_number": 2, "name": "46 Long"},
                    ]
                },
            },
        )
        db.session.add(movie)
        db.session.commit()

        MovieService.save_progress(
            movie,
            season=1,
            episode=1,
            current_seconds=1200,
            duration_seconds=1200,
            completed=True,
        )

        workspace = tv_show_workspace(movie)

        assert workspace["resume_target"]["mode"] == "next"
        assert workspace["resume_target"]["season"] == 1
        assert workspace["resume_target"]["episode"] == 2


def test_tv_show_workspace_prefers_newer_metadata_waypoint_over_stale_partial_progress(app):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            metadata_state={
                "season": 4,
                "episode": 1,
                "tv_total_seasons": 4,
                "tv_total_episodes": 4,
                "tv_seasons": [
                    {"season_number": 2, "name": "Season 2", "episode_count": 1, "poster_url": ""},
                    {"season_number": 4, "name": "Season 4", "episode_count": 1, "poster_url": ""},
                ],
                "tv_episodes": {
                    "2": [{"season_number": 2, "episode_number": 1, "name": "S2 opener"}],
                    "4": [{"season_number": 4, "episode_number": 1, "name": "For All Debts Public and Private"}],
                },
            },
        )
        db.session.add(movie)
        db.session.commit()

        MovieService.save_progress(
            movie,
            season=2,
            episode=1,
            current_seconds=41,
            duration_seconds=2940,
            completed=False,
        )

        workspace = tv_show_workspace(movie)

        assert workspace["resume_target"]["mode"] == "current"
        assert workspace["resume_target"]["season"] == 4
        assert workspace["resume_target"]["episode"] == 1


def test_tv_show_workspace_marks_prior_seasons_complete_from_current_waypoint(app):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            metadata_state={
                "season": 4,
                "episode": 1,
                "tv_total_seasons": 4,
                "tv_total_episodes": 4,
                "tv_seasons": [
                    {"season_number": 1, "name": "Season 1", "episode_count": 1, "poster_url": ""},
                    {"season_number": 2, "name": "Season 2", "episode_count": 1, "poster_url": ""},
                    {"season_number": 3, "name": "Season 3", "episode_count": 1, "poster_url": ""},
                    {"season_number": 4, "name": "Season 4", "episode_count": 1, "poster_url": ""},
                ],
                "tv_episodes": {
                    "1": [{"season_number": 1, "episode_number": 1, "name": "S1 opener"}],
                    "2": [{"season_number": 2, "episode_number": 1, "name": "S2 opener"}],
                    "3": [{"season_number": 3, "episode_number": 1, "name": "S3 opener"}],
                    "4": [{"season_number": 4, "episode_number": 1, "name": "S4 opener"}],
                },
            },
        )
        db.session.add(movie)
        db.session.commit()

        workspace = tv_show_workspace(movie)

        seasons = {item["season_number"]: item for item in workspace["seasons"]}
        assert workspace["completed_seasons"] == 3
        assert workspace["watched_episodes"] == 3
        assert seasons[1]["completion_percent"] == 100
        assert seasons[2]["completion_percent"] == 100
        assert seasons[3]["completion_percent"] == 100
        assert seasons[4]["completion_percent"] == 0


def test_tv_season_workspace_marks_prior_episodes_in_same_season_watched_from_jump_waypoint(app):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            metadata_state={
                "season": 5,
                "episode": 7,
                "tv_total_seasons": 5,
                "tv_total_episodes": 11,
                "tv_seasons": [
                    {"season_number": 1, "name": "Season 1", "episode_count": 1, "poster_url": ""},
                    {"season_number": 2, "name": "Season 2", "episode_count": 1, "poster_url": ""},
                    {"season_number": 3, "name": "Season 3", "episode_count": 1, "poster_url": ""},
                    {"season_number": 4, "name": "Season 4", "episode_count": 1, "poster_url": ""},
                    {"season_number": 5, "name": "Season 5", "episode_count": 7, "poster_url": ""},
                ],
                "tv_episodes": {
                    "1": [{"season_number": 1, "episode_number": 1, "name": "S1 opener"}],
                    "2": [{"season_number": 2, "episode_number": 1, "name": "S2 opener"}],
                    "3": [{"season_number": 3, "episode_number": 1, "name": "S3 opener"}],
                    "4": [{"season_number": 4, "episode_number": 1, "name": "S4 opener"}],
                    "5": [
                        {"season_number": 5, "episode_number": 1, "name": "S5E1"},
                        {"season_number": 5, "episode_number": 2, "name": "S5E2"},
                        {"season_number": 5, "episode_number": 3, "name": "S5E3"},
                        {"season_number": 5, "episode_number": 4, "name": "S5E4"},
                        {"season_number": 5, "episode_number": 5, "name": "S5E5"},
                        {"season_number": 5, "episode_number": 6, "name": "S5E6"},
                        {"season_number": 5, "episode_number": 7, "name": "S5E7"},
                    ],
                },
            },
        )
        db.session.add(movie)
        db.session.commit()

        workspace = tv_season_workspace(movie, season_number=5)

        watched_flags = {
            item["episode_number"]: bool(item["progress"] and item["progress"]["completed"])
            for item in workspace["episodes"]
        }
        assert workspace["season"]["watched_episode_count"] == 6
        assert workspace["season"]["completion_percent"] == 86
        assert watched_flags[1] is True
        assert watched_flags[6] is True
        assert watched_flags[7] is False
