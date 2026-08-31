import pytest

from app.extensions import db
from app.history.models import HistoryEvent
from app.movies.models import Movie
from app.playback.models import PlaybackAttempt, PlaybackSource
from app.playback.providers import ProviderProbeResult
from app.playback.services import (
    PlaybackAttemptService,
    PlaybackService,
    ProviderAvailabilityService,
)


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


def test_provider_preferences_cannot_enable_background_checks(app):
    with app.app_context():
        preference = PlaybackService.save_provider_preference(
            provider="vidlove",
            enabled=True,
            priority=14,
            background_checks=True,
        )

        assert preference.background_checks is False
        assert PlaybackService.provider_preferences({"vidlove"})["vidlove"][
            "background_checks"
        ] is False

        preference.background_checks = True
        db.session.commit()
        assert PlaybackService.provider_preferences({"vidlove"})["vidlove"][
            "background_checks"
        ] is False


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
                "player_metadata": {
                    "quality": "",
                    "codec": "",
                    "playback": "",
                    "size": "",
                    "hdr": False,
                },
                "enabled": True,
                "source_type_label": "Local runtime source",
                "priority": None,
                "availability_status": "UNKNOWN",
                "availability_checked": False,
                "availability_fresh": False,
            }
        ]


def test_indexed_embed_source_exposes_recorded_health_without_probing(app):
    with app.app_context():
        movie = add_movie()
        source = PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="videotube",
            provider_asset_id="selector-health",
            label="VideoTube selector",
        )
        ProviderAvailabilityService.record(
            source,
            ProviderProbeResult(status="AVAILABLE", probe_level="REACHABLE"),
        )

        items = PlaybackService.indexed_embed_sources(
            movie.id, provider_priorities={"videotube": 25}
        )

    assert items[0]["source_type_label"] == "Authorized embed mapping"
    assert items[0]["priority"] == 25
    assert items[0]["availability_status"] == "AVAILABLE"
    assert items[0]["availability_checked"] is True
    assert items[0]["availability_fresh"] is True


def test_playback_attempt_history_updates_one_explicit_attempt_and_summarizes(app, admin_user):
    with app.app_context():
        movie = add_movie()
        started = PlaybackAttemptService.record(
            user_id=admin_user.id,
            movie_id=movie.id,
            provider="vidlove",
            content_id=movie.id,
            scope_key="movie",
            client_attempt_id="attempt-1",
            outcome="started",
            device_id="device-1",
        )
        ready = PlaybackAttemptService.record(
            user_id=admin_user.id,
            movie_id=movie.id,
            provider="vidlove",
            content_id=movie.id,
            scope_key="movie",
            client_attempt_id="attempt-1",
            outcome="embed_ready",
            startup_ms=840,
        )
        finished = PlaybackAttemptService.record(
            user_id=admin_user.id,
            movie_id=movie.id,
            provider="vidlove",
            content_id=movie.id,
            scope_key="movie",
            client_attempt_id="attempt-1",
            outcome="success",
            server_id="provider-owned-value",
        )
        failed = PlaybackAttemptService.record(
            user_id=admin_user.id,
            movie_id=movie.id,
            provider="vidlove",
            content_id=movie.id,
            scope_key="movie",
            client_attempt_id="attempt-2",
            outcome="failure",
            failure_reason="provider timeout",
        )

        assert started.id == ready.id == finished.id
        assert finished.success is True
        assert finished.startup_ms == 840
        assert finished.server_id == "provider-owned-value"
        assert failed.success is False
        assert db.session.scalar(
            db.select(db.func.count(PlaybackAttempt.id)).where(
                PlaybackAttempt.movie_id == movie.id
            )
        ) == 2

        summary = PlaybackAttemptService.recent_summary(user_id=admin_user.id)["vidlove"]

    assert summary == {
        "provider": "vidlove",
        "attempts": 2,
        "successes": 1,
        "failures": 1,
        "avg_startup_ms": 840,
        "last_success_at": summary["last_success_at"],
    }


def test_provider_scores_prefer_recent_success_and_title_history(app, admin_user):
    with app.app_context():
        movie = add_movie()
        for index in range(3):
            PlaybackAttemptService.record(
                user_id=admin_user.id,
                movie_id=movie.id,
                provider="vidlove",
                content_id=movie.id,
                scope_key="movie",
                client_attempt_id=f"vidlove-score-{index}",
                outcome="success",
                startup_ms=700,
            )
        PlaybackAttemptService.record(
            user_id=admin_user.id,
            movie_id=movie.id,
            provider="cinesrc",
            content_id=movie.id,
            scope_key="movie",
            client_attempt_id="cinesrc-score-1",
            outcome="failure",
            failure_reason="not playable",
        )

        scores = PlaybackAttemptService.provider_scores(
            user_id=admin_user.id,
            movie_id=movie.id,
            scope_key="movie",
            provider_keys={"vidlove", "cinesrc", "vidsrc"},
        )

    assert scores["vidlove"]["successes"] == 3
    assert scores["vidlove"]["title_successes"] == 3
    assert scores["vidlove"]["avg_startup_ms"] == 700
    assert scores["vidlove"]["score"] > scores["cinesrc"]["score"]
    assert scores["vidsrc"]["score"] == 0.0


def test_provider_scores_use_language_and_quality_only_for_declared_metadata(app, admin_user):
    with app.app_context():
        movie = add_movie()
        PlaybackAttemptService.record(
            user_id=admin_user.id,
            movie_id=movie.id,
            provider="provider-a",
            content_id=movie.id,
            scope_key="movie",
            client_attempt_id="metadata-a",
            outcome="success",
            language="fr",
            quality="1080p",
            startup_ms=700,
        )
        PlaybackAttemptService.record(
            user_id=admin_user.id,
            movie_id=movie.id,
            provider="provider-b",
            content_id=movie.id,
            scope_key="movie",
            client_attempt_id="metadata-b",
            outcome="success",
            language="en",
            quality="720p",
            startup_ms=700,
        )
        PlaybackAttemptService.record(
            user_id=admin_user.id,
            movie_id=movie.id,
            provider="provider-c",
            content_id=movie.id,
            scope_key="movie",
            client_attempt_id="metadata-c",
            outcome="success",
            language="original",
            quality="1440p",
            startup_ms=700,
        )

        scores = PlaybackAttemptService.provider_scores(
            user_id=admin_user.id,
            movie_id=movie.id,
            scope_key="movie",
            provider_keys={"provider-a", "provider-b"},
            preferred_language="fr",
            preferred_quality="1080p",
            metadata_capabilities={
                "provider-a": {"language": True, "quality": True},
                "provider-b": {"language": False, "quality": False},
            },
        )
        best_scores = PlaybackAttemptService.provider_scores(
            user_id=admin_user.id,
            movie_id=movie.id,
            scope_key="movie",
            provider_keys={"provider-a", "provider-b", "provider-c"},
            preferred_language="original",
            preferred_quality="best",
            metadata_capabilities={
                "provider-a": {"language": True, "quality": True},
                "provider-b": {"language": False, "quality": False},
                "provider-c": {"language": True, "quality": True},
            },
        )
        metadata_only_movie = add_movie()
        metadata_only_scores = PlaybackAttemptService.provider_scores(
            user_id=admin_user.id,
            movie_id=metadata_only_movie.id,
            scope_key="movie",
            provider_keys={"provider-a", "provider-b"},
            preferred_language="fr",
            preferred_quality="1080p",
            metadata_capabilities={
                "provider-a": {"language": True, "quality": True},
                "provider-b": {"language": True, "quality": True},
            },
            source_metadata={
                "provider-a": [{"language": "fr", "quality": "1080p"}],
                "provider-b": [{"language": "en", "quality": "720p"}],
            },
        )

    assert scores["provider-a"]["language_matches"] == 1
    assert scores["provider-a"]["quality_matches"] == 1
    assert scores["provider-b"]["language_matches"] == 0
    assert scores["provider-b"]["quality_matches"] == 0
    assert scores["provider-a"]["score"] > scores["provider-b"]["score"]
    assert best_scores["provider-c"]["language_matches"] == 1
    assert best_scores["provider-c"]["quality_matches"] == 1
    assert best_scores["provider-b"]["quality_matches"] == 0
    assert metadata_only_scores["provider-a"]["score"] > metadata_only_scores["provider-b"]["score"]


def test_last_good_server_memory_is_opaque_and_scoped(app, admin_user):
    with app.app_context():
        movie = add_movie()
        PlaybackAttemptService.record(
            user_id=admin_user.id,
            movie_id=movie.id,
            provider="vidlove",
            content_id=movie.id,
            scope_key="movie",
            client_attempt_id="server-memory-movie",
            outcome="success",
            server_id="provider-native-opaque-movie",
        )
        PlaybackAttemptService.record(
            user_id=admin_user.id,
            movie_id=movie.id,
            provider="vidlove",
            content_id=movie.id,
            scope_key="s01e02",
            client_attempt_id="server-memory-episode",
            outcome="success",
            server_id="provider-native-opaque-episode",
        )
        PlaybackAttemptService.record(
            user_id=admin_user.id,
            movie_id=movie.id,
            provider="vidlove",
            content_id=movie.id,
            scope_key="movie",
            client_attempt_id="server-memory-failure",
            outcome="failure",
            server_id="must-not-be-remembered",
        )

        assert PlaybackAttemptService.last_good_server_id(
            user_id=admin_user.id,
            provider="vidlove",
            movie_id=movie.id,
            scope_key="movie",
        ) == "provider-native-opaque-movie"
        assert PlaybackAttemptService.last_good_server_id(
            user_id=admin_user.id,
            provider="vidlove",
            movie_id=movie.id,
            scope_key="s01e02",
        ) == "provider-native-opaque-episode"
        assert PlaybackAttemptService.last_good_server_id(
            user_id=admin_user.id + 1,
            provider="vidlove",
            movie_id=movie.id,
            scope_key="movie",
        ) == ""
