from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.auth.models import User
from app.extensions import db
from app.history.models import HistoryEvent
from app.movies.models import Movie, MovieProgress
from app.movies.repositories import MovieRepository
from app.movies.services import (
    MovieService,
    ProgressConflictError,
    completion_threshold,
    movie_item,
    parse_movie_filters,
    tv_season_workspace,
    tv_show_workspace,
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


def test_movie_item_exposes_human_readable_genre_names():
    movie = Movie(
        title="Genre test",
        normalized_title="genre test",
        genres=[{"name": "Drama"}, {"name": "Science Fiction"}],
    )

    item = movie_item(movie)

    assert item["genre_names"] == ["Drama", "Science Fiction"]


def test_movie_repository_keeps_a_500_title_library_page_bounded(app):
    with app.app_context():
        db.session.add_all(
            [
                Movie(
                    title=f"Library title {index:03d}",
                    normalized_title=f"library title {index:03d}",
                )
                for index in range(500)
            ]
        )
        db.session.commit()

        items, total = MovieRepository.list(
            {"sort": "title_asc"},
            limit=24,
            offset=24,
        )

    assert total == 500
    assert len(items) == 24
    assert items[0].title == "Library title 024"


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


def test_movies_activity_records_only_meaningful_idempotent_facts(app):
    with app.app_context():
        owner = User(username="activity-owner", password_hash="unused")
        movie = _movie()
        db.session.add_all([owner, movie])
        db.session.commit()

        MovieService.save_progress(movie, current_seconds=10, duration_seconds=100, completed=False)
        MovieService.save_progress(movie, current_seconds=20, duration_seconds=100, completed=False)
        MovieService.save_progress(movie, current_seconds=95, duration_seconds=100, completed=False)
        MovieService.save_progress(movie, current_seconds=100, duration_seconds=100, completed=False)
        MovieService.set_score(movie, 4.5, label="great movie")
        MovieService.set_score(movie, 4.5, label="great movie")
        custom_list = MovieService.create_custom_list(owner.id, title="Activity list")
        MovieService.add_to_custom_list(custom_list, movie)
        MovieService.add_to_custom_list(custom_list, movie)

        events = list(db.session.scalars(db.select(HistoryEvent).order_by(HistoryEvent.event_type)))

    assert [event.event_type for event in events] == [
        "list_membership_added",
        "movie_completed",
        "rating",
    ]


def test_v2_identity_and_library_entry_keep_movie_and_tv_separate(app):
    with app.app_context():
        movie = Movie(
            title="Twin",
            normalized_title="twin movie",
            media_type="movie",
            external_ids={"tmdb_id": "42", "tmdb_type": "movie"},
        )
        show = Movie(
            title="Twin",
            normalized_title="twin show",
            media_type="tv",
            external_ids={"tmdb_id": "42", "tmdb_type": "tv"},
        )
        local = Movie(title="Local", normalized_title="local", media_type="movie")
        db.session.add_all([movie, show, local])
        db.session.commit()

        assert movie.media_key == "movie:42"
        assert show.media_key == "tv:42"
        assert local.media_key == f"local:movie:{local.id}"

        MovieService.set_status(movie, "watched")
        MovieService.set_score(movie, 4.5, label="Favorite Movie")
        assert movie.library_entry is not None
        assert movie.library_entry.lifecycle_status == "watched"
        assert movie.library_entry.personal_rating == 4.5
        assert movie.library_entry.personal_label == "Favorite Movie"
        assert movie.library_entry.is_favorite is False


def test_progress_completion_thresholds_and_manual_unwatched_are_centralized(app):
    with app.app_context():
        film = Movie(title="Film", normalized_title="film")
        show = Movie(title="Show", normalized_title="show", media_type="tv")
        ended = Movie(title="Ended", normalized_title="ended")
        db.session.add_all([film, show, ended])
        db.session.commit()

        assert completion_threshold() == 0.95
        assert completion_threshold(season=1, episode=1) == 0.90
        below = MovieService.save_progress(
            film,
            current_seconds=94,
            duration_seconds=100,
            completed=False,
        )
        assert below.completed is False
        assert film.library_entry.lifecycle_status == "watching"

        complete = MovieService.save_progress(
            film,
            current_seconds=95,
            duration_seconds=100,
            completed=False,
        )
        assert complete.completed is True
        assert film.library_entry.lifecycle_status == "watched"

        MovieService.set_status(film, "want_to_watch")
        assert film.library_entry.completed_at is None
        assert film.library_entry.lifecycle_status == "want_to_watch"

        episode = MovieService.save_progress(
            show,
            season=1,
            episode=1,
            current_seconds=90,
            duration_seconds=100,
            completed=False,
        )
        special = MovieService.save_progress(
            show,
            season=0,
            episode=1,
            current_seconds=1,
            duration_seconds=100,
            completed=False,
        )
        ended_progress = MovieService.save_progress(
            ended,
            current_seconds=0,
            duration_seconds=0,
            completed=False,
            ended=True,
        )
        assert episode.completed is True
        assert special.completed is False
        assert ended_progress.completed is True
        assert ended.library_entry.lifecycle_status == "watched"


def test_progress_scope_is_unique_and_watch_selection_is_personal_only(app):
    with app.app_context():
        available = Movie(title="Available", normalized_title="available")
        watched = Movie(title="Watched", normalized_title="watched")
        db.session.add_all([available, watched])
        db.session.commit()
        MovieService.set_status(available, "want_to_watch")
        MovieService.set_status(watched, "watched")

        first = MovieProgress(movie_id=available.id, current_seconds=10)
        db.session.add(first)
        db.session.commit()
        db.session.add(MovieProgress(movie_id=available.id, current_seconds=20))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        selection = MovieService.what_should_i_watch()
        assert selection is not None
        assert selection["id"] == available.id
        assert selection["eligibility_reason"] == "From your personal unwatched library."


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
    assert result["items"][0]["overview"] == "Two stories of love and chance in Hong Kong."
    assert result["items"][0]["recommendation_explanation"]["confidence"] == "high"
    assert "Same director" in result["items"][0]["recommendation_reason"]
    assert result["summary"]["excluded_watched"] == 2


def test_what_should_i_watch_filters_only_personal_unwatched_entries(app):
    with app.app_context():
        matching = Movie(
            title="Short French film",
            normalized_title="short french film",
            media_type="movie",
            year=1998,
            runtime_minutes=94,
            genres=[{"name": "Drama"}],
            metadata_state={"tmdb_detail": {"original_language": "fr"}},
        )
        nonmatching = Movie(
            title="Long series",
            normalized_title="long series",
            media_type="tv",
            year=2014,
            runtime_minutes=55,
            genres=[{"name": "Drama"}],
            metadata_state={"tmdb_detail": {"original_language": "en"}},
        )
        watched = Movie(title="Watched", normalized_title="watched", year=1996)
        db.session.add_all([matching, nonmatching, watched])
        db.session.commit()
        MovieService.set_status(matching, "want_to_watch")
        MovieService.set_status(nonmatching, "want_to_watch")
        MovieService.set_status(watched, "watched")

        selection = MovieService.what_should_i_watch(
            media_type="movie",
            genre="Drama",
            runtime_max=100,
            language="fr",
            decade=1990,
            sort="oldest_added",
        )

    assert selection is not None
    assert selection["id"] == matching.id
    assert selection["eligibility_reason"] == (
        "Unwatched in your personal library; matches movie, Drama genre, up to 100 min, "
        "FR original language, 1990s."
    )


def test_because_you_watched_uses_cached_related_cards_and_excludes_local_titles(app):
    with app.app_context():
        anchor = Movie(
            title="Anchor",
            normalized_title="anchor",
            status="watched",
            external_ids={"tmdb_id": "100", "tmdb_type": "movie"},
            metadata_state={
                "tmdb_detail": {
                    "recommendations": [
                        {"tmdb_id": 200, "media_type": "movie", "title": "Already local"},
                        {"tmdb_id": 201, "media_type": "movie", "title": "Cached recommendation"},
                    ],
                    "similar": [
                        {"tmdb_id": 202, "media_type": "movie", "title": "Cached similar"},
                    ],
                }
            },
        )
        duplicate = Movie(
            title="Already local",
            normalized_title="already local",
            external_ids={"tmdb_id": "200", "tmdb_type": "movie"},
        )
        db.session.add_all([anchor, duplicate])
        db.session.commit()
        MovieService.set_status(anchor, "watched")

        rail = MovieService.because_you_watched()

    assert rail is not None
    assert rail["anchor"]["id"] == anchor.id
    assert [item["tmdb_id"] for item in rail["items"]] == [201, 202]
    assert rail["items"][0]["signal"] == "TMDB recommendation"
    assert rail["items"][0]["detail_url"] == "/movies/discover/movie/201"


def test_because_you_watched_sorts_mixed_datetime_shapes_in_utc(app, monkeypatch):
    with app.app_context():
        newer = Movie(
            id="mov_aware",
            media_key="movie:100",
            title="Newer anchor",
            normalized_title="newer anchor",
            media_type="movie",
            status="watched",
            updated_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
            metadata_state={
                "tmdb_detail": {
                    "similar": [{"tmdb_id": 201, "title": "Related title"}]
                }
            },
        )
        older = Movie(
            id="mov_naive",
            media_key="movie:101",
            title="Older anchor",
            normalized_title="older anchor",
            media_type="movie",
            status="watched",
            updated_at=datetime(2026, 8, 26, 12),
        )
        monkeypatch.setattr(db.session, "scalars", lambda _statement: [older, newer])

        rail = MovieService.because_you_watched()

    assert rail is not None
    assert rail["anchor"]["id"] == newer.id


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


def test_tv_season_workspace_uses_the_next_real_normal_season_episode(app):
    with app.app_context():
        movie = Movie(
            title="Example Series",
            normalized_title="example series",
            media_type="tv",
            metadata_state={
                "tv_seasons": [
                    {"season_number": 0, "name": "Specials", "episode_count": 1},
                    {"season_number": 1, "name": "Season 1", "episode_count": 1},
                    {"season_number": 2, "name": "Season 2", "episode_count": 1},
                ],
                "tv_episodes": {
                    "0": [{"season_number": 0, "episode_number": 1, "name": "Bonus"}],
                    "1": [{"season_number": 1, "episode_number": 1, "name": "Finale"}],
                    "2": [{"season_number": 2, "episode_number": 1, "name": "Premiere"}],
                },
            },
        )
        db.session.add(movie)
        db.session.commit()

        workspace = tv_season_workspace(movie, season_number=1, selected_episode=1)
        specials = tv_season_workspace(movie, season_number=0, selected_episode=1)

        assert workspace["next_episode"] == {
            "season_number": 2,
            "episode_number": 1,
            "name": "Premiere",
        }
        assert specials["next_episode"] is None


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
