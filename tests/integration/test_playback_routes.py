from io import BytesIO
from urllib.parse import urlsplit

import pytest

from app.extensions import db
from app.movies.models import Movie
from app.playback.models import PlaybackSource, ProviderAvailability
from app.playback.providers import INDEXED_EMBED_PROVIDER_SPECS, ProviderProbeResult
from app.playback.services import PlaybackService, ProviderAvailabilityService
from app.playback.subtitles import SubtitleCandidate
from tests.conftest import csrf_from


def test_playback_routes_are_hidden_when_disabled(authenticated_client, app):
    with app.app_context():
        movie = Movie(title="Hidden Playback", normalized_title="hidden playback")
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id
    response = authenticated_client.get(f"/playback/movie/{movie_id}")
    assert response.status_code == 404
    detail = authenticated_client.get(f"/movies/{movie_id}").get_data(as_text=True)
    assert "Playback sources" not in detail


def test_magnet_route_is_hidden_independently(authenticated_client, app):
    with app.app_context():
        movie = Movie(title="Flags", normalized_title="flags")
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id
    app.config["DRAGON_PLAYBACK_ENABLED"] = True
    app.config["DRAGON_MAGNETS_ENABLED"] = False
    page = authenticated_client.get(f"/playback/movie/{movie_id}")
    assert page.status_code == 200
    assert "disabled by default" in page.get_data(as_text=True)
    response = authenticated_client.post(
        f"/playback/movie/{movie_id}/magnets",
        data={
            "magnet_uri": "magnet:?xt=urn:btih:x",
            "csrf_token": csrf_from(page),
        },
    )
    assert response.status_code == 404


def test_vidsrc_is_click_gated_and_resolved_by_protected_playback_route(authenticated_client, app):
    with app.app_context():
        movie = Movie(
            title="Arrival",
            normalized_title="arrival",
            external_ids={"imdb_id": "tt2543164"},
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config["DRAGON_PLAYBACK_ENABLED"] = True
    app.config["DRAGON_VIDSRC_ENABLED"] = True
    app.config["DRAGON_VIDSRC_EMBED_URL"] = "https://vsembed.ru/embed"

    detail = authenticated_client.get(f"/movies/{movie_id}")
    detail_html = detail.get_data(as_text=True)
    assert "Play with VidSrc" in detail_html
    assert "https://vsembed.ru" not in detail_html
    assert "sandbox=" not in detail_html
    assert "frame-src 'self' https://vsembed.ru" in detail.headers["Content-Security-Policy"]

    response = authenticated_client.get(f"/playback/movie/{movie_id}/vidsrc")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    source_payload = response.get_json()["source"]
    source_id = source_payload.pop("source_id")
    assert source_id.startswith("src_")
    assert source_payload == {
        "provider": "vidsrc",
        "label": "VidSrc",
        "url": "https://vsembed.ru/embed/tt2543164",
        "match": "imdb",
    }

    anonymous = app.test_client().get(f"/playback/movie/{movie_id}/vidsrc")
    assert anonymous.status_code == 302


def test_vidsrc_resolves_and_caches_external_ids(authenticated_client, app):
    class StubIdentityProvider:
        def resolve(self, **values):
            assert values == {
                "title": "Great Teacher Onizuka",
                "year": 1999,
                "media_type": "movie",
                "external_ids": {},
            }
            return {
                "tmdb_id": "43017",
                "tmdb_type": "tv",
                "imdb_id": "tt0315008",
            }

    with app.app_context():
        movie = Movie(
            title="Great Teacher Onizuka",
            normalized_title="great teacher onizuka",
            year=1999,
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config["DRAGON_PLAYBACK_ENABLED"] = True
    app.config["DRAGON_VIDSRC_ENABLED"] = True
    app.config["DRAGON_VIDSRC_EMBED_URL"] = "https://vsembed.ru/embed"
    app.extensions["dragon_tmdb_identity_provider"] = StubIdentityProvider()

    response = authenticated_client.get(f"/playback/movie/{movie_id}/vidsrc")

    assert response.status_code == 200
    assert response.get_json()["source"]["url"] == ("https://vsembed.ru/embed/tt0315008")
    with app.app_context():
        assert db.session.get(Movie, movie_id).external_ids == {
            "tmdb_id": "43017",
            "tmdb_type": "tv",
            "imdb_id": "tt0315008",
        }


def test_vidsrc_tv_episode_uses_scope_and_materializes_a_source(authenticated_client, app):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            external_ids={"tmdb_id": "1399", "tmdb_type": "tv"},
            metadata_state={
                "tv_episodes": {
                    "2": [{"season_number": 2, "episode_number": 5, "name": "Big Girls"}]
                }
            },
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_VIDSRC_ENABLED=True,
        DRAGON_VIDSRC_EMBED_URL="https://vsembed.ru/embed",
    )

    response = authenticated_client.get(f"/playback/movie/{movie_id}/vidsrc?season=2&episode=5")

    assert response.status_code == 200
    source_payload = response.get_json()["source"]
    source_id = source_payload.pop("source_id")
    assert source_id.startswith("src_")
    assert source_payload == {
        "provider": "vidsrc",
        "label": "VidSrc",
        "url": "https://vsembed.ru/embed/tv/1399/2-5",
        "match": "tmdb",
    }
    with app.app_context():
        source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie_id,
                PlaybackSource.provider == "vidsrc",
            )
        )
        assert source is not None
        assert source.scope_key == "s02e05"
        assert source.provider_asset_id == "1399"
        assert source.locator == "1399"
        assert source.kind == "embed"
        availability = db.session.scalar(
            db.select(ProviderAvailability).where(
                ProviderAvailability.playback_source_id == source.id
            )
        )
        assert availability is not None
        assert availability.status == "UNKNOWN"


def test_vidsrc_rejects_invalid_tv_scope(authenticated_client, app):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            external_ids={"imdb_id": "tt0141842"},
            metadata_state={"tv_episodes": {"1": [{"episode_number": 1}]}},
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config.update(DRAGON_PLAYBACK_ENABLED=True, DRAGON_VIDSRC_ENABLED=True)

    response = authenticated_client.get(f"/playback/movie/{movie_id}/vidsrc?season=1")

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_playback_scope"


def test_vidsrc_v2_redirect_hosts_are_allowed_by_csp(authenticated_client, app):
    app.config["DRAGON_VIDSRC_ENABLED"] = True
    app.config["DRAGON_VIDSRC_EMBED_URL"] = "https://v2.vidsrc.me/embed"

    response = authenticated_client.get("/")

    policy = response.headers["Content-Security-Policy"]
    assert "frame-src 'self' https://v2.vidsrc.me https://vidsrc.me https://vidsrcme.ru" in policy


def test_csp_does_not_allow_credentialed_embed_templates(authenticated_client, app):
    app.config.update(
        DRAGON_VIDSRC_ENABLED=True,
        DRAGON_VIDSRC_EMBED_URL="https://user:pass@vidsrc.example/embed",
        DRAGON_VIDEOTUBE_ENABLED=True,
        DRAGON_VIDEOTUBE_EMBED_URL="https://user:pass@down.vidtube.one/embed-{asset_id}.html",
    )

    response = authenticated_client.get("/")

    policy = response.headers["Content-Security-Policy"]
    assert "user:pass" not in policy
    assert "https://vidsrc.example" not in policy
    assert "https://down.vidtube.one" not in policy


def test_authorized_indexed_embed_is_listed_and_resolved_through_its_provider(
    authenticated_client, app
):
    with app.app_context():
        movie = Movie(title="Arrival", normalized_title="arrival")
        db.session.add(movie)
        db.session.commit()
        source = PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="videotube",
            provider_asset_id="iuki4kda2u7l",
            label="VideoTube · Arabic Subs",
            subtitle_languages=["ar"],
        )
        movie_id = movie.id
        source_id = source.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_VIDEOTUBE_ENABLED=True,
        DRAGON_VIDEOTUBE_EMBED_URL="https://down.vidtube.one/embed-{asset_id}.html",
    )

    detail = authenticated_client.get(f"/movies/{movie_id}")
    listing = authenticated_client.get(f"/playback/movie/{movie_id}/sources")
    resolved = authenticated_client.get(f"/playback/movie/{movie_id}/sources/{source_id}/embed")

    assert "VideoTube · Arabic Subs" in detail.get_data(as_text=True)
    assert "data-inline-release-browser" not in detail.get_data(as_text=True)
    assert listing.get_json()["items"][0]["provider"] == "videotube"
    source_payload = resolved.get_json()["source"]
    assert source_payload.pop("source_id") == source_id
    assert source_payload == {
        "provider": "videotube",
        "label": "VideoTube",
        "url": "https://down.vidtube.one/embed-iuki4kda2u7l.html",
        "match": "indexed",
        "sandbox": "allow-scripts allow-forms allow-popups allow-presentation",
    }

    selection = authenticated_client.post(
        f"/playback/movie/{movie_id}/sources/{source_id}/selected",
        data={"csrf_token": csrf_from(detail)},
    )
    assert selection.status_code == 200
    with app.app_context():
        assert PlaybackService.last_selected_source(movie_id).id == source_id


def test_provider_activation_status_reports_local_config_and_mapping_readiness(
    authenticated_client, app
):
    with app.app_context():
        movie = Movie(
            title="Activation smoke test",
            normalized_title="activation smoke test",
            external_ids={"tmdb_id": "950387"},
        )
        db.session.add(movie)
        db.session.commit()
        PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="videotube",
            provider_asset_id="knownasset123",
            label="VideoTube",
            provenance={"origin": "catalog_import"},
        )
        disabled_mapping = PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="updown",
            provider_asset_id="disabledprovider123",
            label="UpDown",
            provenance={"origin": "catalog_import"},
        )
        disabled_mapping.enabled = False
        unapproved_mapping = PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="ok",
            provider_asset_id="7593181055685",
            label="OK.ru",
        )
        unapproved_mapping.authorization_status = "unknown"
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_VIDSRC_ENABLED=True,
        DRAGON_VIDSRC_EMBED_URL="https://vsembed.example/embed",
        DRAGON_VIDEOTUBE_ENABLED=True,
        DRAGON_VIDEOTUBE_EMBED_URL="https://down.vidtube.one/embed-{asset_id}.html",
        DRAGON_UPDOWN_ENABLED=False,
        DRAGON_UPDOWN_EMBED_URL="",
        DRAGON_OK_ENABLED=True,
        DRAGON_OK_EMBED_URL="https://ok.ru/videoembed/{asset_id}",
    )

    response = authenticated_client.get(f"/playback/movie/{movie_id}/activation-status")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    payload = response.get_json()
    assert payload["scope_key"] == "movie"
    providers = {item["provider"]: item for item in payload["providers"]}
    assert providers["videotube"] == {
        "provider": "videotube",
        "label": "VideoTube",
        "configured": True,
        "configuration_reason": "",
        "preference_enabled": True,
        "mapping_count": 1,
        "enabled_mapping_count": 1,
        "authorized_enabled_mapping_count": 1,
        "ready": True,
    }
    assert providers["updown"]["configured"] is False
    assert providers["updown"]["configuration_reason"] == "disabled_in_config"
    assert providers["updown"]["mapping_count"] == 1
    assert providers["updown"]["enabled_mapping_count"] == 0
    assert providers["updown"]["authorized_enabled_mapping_count"] == 0
    assert providers["updown"]["ready"] is False
    assert providers["ok"]["configured"] is True
    assert providers["ok"]["enabled_mapping_count"] == 1
    assert providers["ok"]["authorized_enabled_mapping_count"] == 0
    assert providers["ok"]["ready"] is False
    assert providers["vidsrc"]["identity_ready"] is True
    assert providers["vidsrc"]["ready"] is True
    assert "down.vidtube.one" not in response.get_data(as_text=True)


def test_unapproved_indexed_embed_is_not_listed_or_resolved(authenticated_client, app):
    with app.app_context():
        movie = Movie(title="Unapproved source", normalized_title="unapproved source")
        db.session.add(movie)
        db.session.commit()
        source = PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="videotube",
            provider_asset_id="notapproved123",
            label="VideoTube",
        )
        source.authorization_status = "unknown"
        db.session.commit()
        movie_id = movie.id
        source_id = source.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_VIDEOTUBE_ENABLED=True,
        DRAGON_VIDEOTUBE_EMBED_URL="https://down.vidtube.one/embed-{asset_id}.html",
    )

    listing = authenticated_client.get(f"/playback/movie/{movie_id}/sources")
    resolved = authenticated_client.get(f"/playback/movie/{movie_id}/sources/{source_id}/embed")

    assert listing.status_code == 200
    assert listing.get_json()["items"] == []
    assert resolved.status_code == 404


def test_fresh_unavailable_source_is_hidden_and_cannot_be_played(authenticated_client, app):
    with app.app_context():
        movie = Movie(title="Unavailable embed", normalized_title="unavailable embed")
        db.session.add(movie)
        db.session.commit()
        source = PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="videotube",
            provider_asset_id="iuki4kda2u7l",
            label="VideoTube · unavailable",
        )
        ProviderAvailabilityService.record(source, ProviderProbeResult(status="UNAVAILABLE"))
        movie_id = movie.id
        source_id = source.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_VIDEOTUBE_ENABLED=True,
        DRAGON_VIDEOTUBE_EMBED_URL="https://down.vidtube.one/embed-{asset_id}.html",
    )

    listing = authenticated_client.get(f"/playback/movie/{movie_id}/sources")
    play = authenticated_client.get(f"/playback/movie/{movie_id}/sources/{source_id}/embed")

    assert listing.get_json()["items"] == []
    assert play.status_code == 503
    assert play.get_json()["error"]["code"] == "source_unavailable"


def test_authorized_catalog_import_api_creates_a_report_and_source(authenticated_client, app):
    with app.app_context():
        movie = Movie(
            title="Catalog import",
            normalized_title="catalog import",
            external_ids={"tmdb_id": "950387"},
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config["DRAGON_PLAYBACK_ENABLED"] = True
    page = authenticated_client.get(f"/movies/{movie_id}")
    imported = authenticated_client.post(
        "/playback/catalog/imports",
        json={
            "source_name": "Authorized fixture export",
            "rows": [
                {
                    "tmdb_id": "950387",
                    "media_type": "movie",
                    "provider": "videotube",
                    "provider_asset_id": "catalog-asset",
                }
            ],
        },
        headers={"X-CSRFToken": csrf_from(page)},
    )

    assert imported.status_code == 201, imported.get_json()
    batch = imported.get_json()["batch"]
    report = authenticated_client.get(f"/playback/catalog/imports/{batch['id']}")
    assert batch["accepted_rows"] == 1
    assert batch["rows"][0]["provider"] == "videotube"
    assert report.get_json()["batch"]["rows"][0]["created_playback_source_id"].startswith("src_")


def test_authorized_indexed_mapping_can_be_added_without_an_arbitrary_url(
    authenticated_client, app
):
    with app.app_context():
        movie = Movie(title="Manual Mapping", normalized_title="manual mapping")
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_VIDEOTUBE_ENABLED=True,
        DRAGON_VIDEOTUBE_EMBED_URL="https://down.vidtube.one/embed-{asset_id}.html",
    )
    page = authenticated_client.get(f"/movies/{movie_id}")
    response = authenticated_client.post(
        f"/playback/movie/{movie_id}/sources/indexed",
        data={
            "csrf_token": csrf_from(page),
            "provider": "videotube",
            "provider_asset_id": "iuki4kda2u7l",
            "label": "VideoTube · Arabic Subs",
            "language": "ar",
            "subtitle_languages": "ar,en",
            "quality": "1080p",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Authorized embed mapping saved." in response.get_data(as_text=True)
    listing = authenticated_client.get(f"/playback/movie/{movie_id}/sources")
    assert listing.get_json()["items"] == [
        {
            "id": listing.get_json()["items"][0]["id"],
            "provider": "videotube",
            "label": "VideoTube · Arabic Subs",
            "language": "ar",
            "subtitle_languages": ["ar", "en"],
            "quality": "1080p",
            "playback_mode": "embed",
            "selected": False,
        }
    ]
    with app.app_context():
        source = PlaybackService.last_selected_source(movie_id)
        assert source is None
        saved = db.session.scalar(
            db.select(PlaybackSource).where(PlaybackSource.movie_id == movie_id)
        )
        assert saved.provenance["origin"] == "manual_authorized_import"
        assert saved.locator == "iuki4kda2u7l"


def test_authorized_source_activation_smoke_flow_is_scoped_and_resilient(authenticated_client, app):
    """Exercise the local catalog → selected sources → resolver chain without network I/O."""
    with app.app_context():
        movie = Movie(
            title="Activation Movie",
            normalized_title="activation movie",
            external_ids={"tmdb_id": "1001", "imdb_id": "tt1000001"},
        )
        second_movie = Movie(
            title="Disabled Mapping",
            normalized_title="disabled mapping",
            external_ids={"imdb_id": "tt1000002"},
        )
        tv = Movie(
            title="Activation TV",
            normalized_title="activation tv",
            media_type="tv",
            external_ids={"tmdb_id": "3003", "tmdb_type": "tv"},
            metadata_state={
                "tv_episodes": {
                    "1": [{"season_number": 1, "episode_number": 5, "name": "Episode 5"}]
                }
            },
        )
        db.session.add_all((movie, second_movie, tv))
        db.session.flush()
        db.session.add(
            PlaybackSource(
                movie_id=movie.id,
                kind="magnet",
                label="Local · FHD",
                locator="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
            )
        )
        db.session.commit()
        movie_id = movie.id
        second_movie_id = second_movie.id
        tv_id = tv.id

    rows = [
        {
            "tmdb_id": "1001",
            "media_type": "movie",
            "provider": "videotube",
            "provider_asset_id": "movievideo",
        },
        {
            "tmdb_id": "1001",
            "media_type": "movie",
            "provider": "updown",
            "provider_asset_id": "movieupdown",
        },
        {
            "tmdb_id": "1001",
            "media_type": "movie",
            "provider": "ok",
            "provider_asset_id": "7593181055685",
        },
        {
            "tmdb_id": "1001",
            "media_type": "movie",
            "provider": "videotube",
            "provider_asset_id": "movievideo",
        },
        {
            "imdb_id": "tt1000002",
            "media_type": "movie",
            "provider": "videotube",
            "provider_asset_id": "secondvideo",
        },
        {
            "imdb_id": "tt1000002",
            "media_type": "movie",
            "provider": "updown",
            "provider_asset_id": "secondupdown",
        },
        {
            "tmdb_id": "3003",
            "media_type": "tv",
            "season": 1,
            "episode": 5,
            "provider": "videotube",
            "provider_asset_id": "tvvideo",
        },
        {
            "tmdb_id": "3003",
            "media_type": "tv",
            "season": 1,
            "episode": 5,
            "provider": "updown",
            "provider_asset_id": "tvupdown",
        },
        {
            "tmdb_id": "3003",
            "media_type": "tv",
            "season": 1,
            "episode": 5,
            "provider": "okru",
            "provider_asset_id": "7593181055686",
        },
        {
            "title": "Activation Movie",
            "year": 2025,
            "media_type": "movie",
            "provider": "videotube",
            "provider_asset_id": "weakmatch",
        },
        {
            "tmdb_id": "1001",
            "media_type": "movie",
            "embed_url": "https://unknown.example/embed-nope.html",
        },
        {
            "tmdb_id": "1001",
            "media_type": "movie",
            "provider": "updown",
            "provider_asset_id": "../../invalid",
        },
    ]
    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_VIDSRC_ENABLED=True,
        DRAGON_VIDSRC_EMBED_URL="https://vsembed.ru/embed",
        DRAGON_VIDEOTUBE_ENABLED=True,
        DRAGON_VIDEOTUBE_EMBED_URL="https://down.vidtube.one/embed-{asset_id}.html",
        DRAGON_UPDOWN_ENABLED=True,
        DRAGON_UPDOWN_EMBED_URL="https://updown.icu/embed-{asset_id}-1280x640.html",
        DRAGON_OK_ENABLED=True,
        DRAGON_OK_EMBED_URL="https://ok.ru/videoembed/{asset_id}",
    )
    import_page = authenticated_client.get(f"/movies/{movie_id}")
    imported = authenticated_client.post(
        "/playback/catalog/imports",
        json={"source_name": "synthetic authorized activation smoke", "rows": rows},
        headers={"X-CSRFToken": csrf_from(import_page)},
    )

    assert imported.status_code == 201, imported.get_json()
    batch = imported.get_json()["batch"]
    expected_counts = (12, 9, 1, 2)
    assert (
        batch["total_rows"],
        batch["accepted_rows"],
        batch["review_rows"],
        batch["rejected_rows"],
    ) == expected_counts
    reimported = authenticated_client.post(
        "/playback/catalog/imports",
        json={"source_name": "synthetic authorized activation smoke", "rows": rows},
        headers={"X-CSRFToken": csrf_from(import_page)},
    )
    assert reimported.status_code == 201
    rerun_batch = reimported.get_json()["batch"]
    assert (
        rerun_batch["total_rows"],
        rerun_batch["accepted_rows"],
        rerun_batch["review_rows"],
        rerun_batch["rejected_rows"],
    ) == expected_counts
    with app.app_context():
        movie_sources = list(
            db.session.scalars(
                db.select(PlaybackSource).where(
                    PlaybackSource.movie_id == movie_id,
                    PlaybackSource.kind == "embed",
                )
            )
        )
        assert len(movie_sources) == 3
        assert {source.provider for source in movie_sources} == {"videotube", "updown", "ok"}
        assert all(source.authorization_status == "catalog_authorized" for source in movie_sources)
        assert not any(source.enabled for source in movie_sources)
        assert [item["label"] for item in PlaybackService.player_sources(movie_id)] == [
            "Local · FHD"
        ]

    detail = authenticated_client.get(f"/movies/{movie_id}")
    assert detail.status_code == 200
    assert "down.vidtube.one" not in detail.get_data(as_text=True)
    assert authenticated_client.get(f"/playback/movie/{movie_id}/sources").get_json()["items"] == []
    csrf_token = csrf_from(detail)
    source_ids = {source.provider: source.id for source in movie_sources}
    for source_id in source_ids.values():
        activated = authenticated_client.post(
            f"/playback/movie/{movie_id}/sources/{source_id}/enabled",
            data={"enabled": "true", "csrf_token": csrf_token},
        )
        assert activated.status_code == 200
        assert activated.get_json()["source"]["enabled"] is True

    listed = authenticated_client.get(f"/playback/movie/{movie_id}/sources")
    assert [item["provider"] for item in listed.get_json()["items"]] == [
        "videotube",
        "updown",
        "ok",
    ]
    refreshed = authenticated_client.get(f"/movies/{movie_id}")
    refreshed_html = refreshed.get_data(as_text=True)
    assert all(label in refreshed_html for label in ("VideoTube", "UpDown", "OK.ru"))
    resolved = {
        provider: authenticated_client.get(
            f"/playback/movie/{movie_id}/sources/{source_id}/embed"
        ).get_json()["source"]["url"]
        for provider, source_id in source_ids.items()
    }
    assert resolved == {
        "videotube": "https://down.vidtube.one/embed-movievideo.html",
        "updown": "https://updown.icu/embed-movieupdown-1280x640.html",
        "ok": "https://ok.ru/videoembed/7593181055685",
    }
    assert authenticated_client.get(f"/playback/movie/{movie_id}/vidsrc").status_code == 200

    with app.app_context():
        tv_videotube = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == tv_id,
                PlaybackSource.provider == "videotube",
            )
        )
        assert tv_videotube.scope_key == "s01e05"
        tv_videotube_id = tv_videotube.id
    activated_tv = authenticated_client.post(
        f"/playback/movie/{tv_id}/sources/{tv_videotube_id}/enabled",
        data={"enabled": "true", "csrf_token": csrf_token},
    )
    assert activated_tv.status_code == 200
    tv_sources = authenticated_client.get(
        f"/playback/movie/{tv_id}/sources?season=1&episode=5"
    ).get_json()["items"]
    assert [item["provider"] for item in tv_sources] == ["videotube"]
    assert (
        authenticated_client.get(f"/playback/movie/{second_movie_id}/sources").get_json()["items"]
        == []
    )
    with app.app_context():
        disabled_source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == second_movie_id,
                PlaybackSource.provider == "videotube",
            )
        )
        disabled_source_id = disabled_source.id
    assert (
        authenticated_client.get(
            f"/playback/movie/{second_movie_id}/sources/{disabled_source_id}/embed"
        ).status_code
        == 404
    )

    app.config["DRAGON_UPDOWN_EMBED_URL"] = "https://invalid.example/embed-{asset_id}.html"
    app.extensions.pop("dragon_playback_provider_registry", None)
    resilient = authenticated_client.get(f"/playback/movie/{movie_id}/sources")
    assert resilient.status_code == 200
    assert [item["provider"] for item in resilient.get_json()["items"]] == ["videotube", "ok"]
    assert (
        authenticated_client.get(
            f"/playback/movie/{movie_id}/sources/{source_ids['updown']}/embed"
        ).status_code
        == 409
    )


def test_disabled_indexed_embed_provider_is_not_exposed(authenticated_client, app):
    with app.app_context():
        movie = Movie(title="Disabled VideoTube", normalized_title="disabled videotube")
        db.session.add(movie)
        db.session.commit()
        PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="videotube",
            provider_asset_id="iuki4kda2u7l",
            label="VideoTube · Arabic Subs",
        )
        movie_id = movie.id

    app.config.update(DRAGON_PLAYBACK_ENABLED=True, DRAGON_VIDEOTUBE_ENABLED=False)

    detail = authenticated_client.get(f"/movies/{movie_id}")
    listing = authenticated_client.get(f"/playback/movie/{movie_id}/sources")

    assert "VideoTube · Arabic Subs" not in detail.get_data(as_text=True)
    assert listing.get_json()["items"] == []


def test_playback_settings_disable_a_provider_and_apply_its_preference(authenticated_client, app):
    with app.app_context():
        movie = Movie(title="Provider Preferences", normalized_title="provider preferences")
        db.session.add(movie)
        db.session.commit()
        source = PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="videotube",
            provider_asset_id="iuki4kda2u7l",
            label="VideoTube · Arabic Subs",
        )
        movie_id = movie.id
        source_id = source.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_VIDEOTUBE_ENABLED=True,
        DRAGON_VIDEOTUBE_EMBED_URL="https://down.vidtube.one/embed-{asset_id}.html",
    )

    settings_page = authenticated_client.get("/settings/playback")
    response = authenticated_client.post(
        "/settings/playback/providers/videotube",
        data={
            "csrf_token": csrf_from(settings_page),
            "priority": "25",
        },
        follow_redirects=True,
    )
    detail = authenticated_client.get(f"/movies/{movie_id}")
    source_response = authenticated_client.get(
        f"/playback/movie/{movie_id}/sources/{source_id}/embed"
    )

    assert response.status_code == 200
    assert "Playback provider preference saved." in response.get_data(as_text=True)
    assert "VideoTube · Arabic Subs" not in detail.get_data(as_text=True)
    assert source_response.status_code == 409
    with app.app_context():
        preferences = PlaybackService.provider_preferences({"videotube"})
    assert preferences["videotube"] == {
            "provider": "videotube",
            "enabled": False,
            "priority": 25,
            "background_checks": False,
        }


def test_authorized_catalog_settings_page_imports_and_activates_one_mapping(
    authenticated_client, app
):
    with app.app_context():
        movie = Movie(
            title="Production Catalog Fixture",
            normalized_title="production catalog fixture",
            external_ids={"tmdb_id": "603", "imdb_id": "tt0133093"},
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config["DRAGON_PLAYBACK_ENABLED"] = True
    page = authenticated_client.get("/settings/playback/catalog")
    assert page.status_code == 200
    page_html = page.get_data(as_text=True)
    assert "Authorized source catalog" in page_html
    assert "VideoTube" in page_html
    assert "UpDown" in page_html
    assert "OK.ru" in page_html
    assert page_html.count("Not configured") == 3

    catalog = (
        "media_type,tmdb_id,imdb_id,season,episode,provider_key,asset_id\n"
        "movie,603,tt0133093,,,videotube,iuki4kda2u7l\n"
    )
    imported = authenticated_client.post(
        "/settings/playback/catalog/imports",
        data={
            "csrf_token": csrf_from(page),
            "source_name": "Production smoke fixture",
            "catalog": (BytesIO(catalog.encode()), "authorized-fixture.csv"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    html = imported.get_data(as_text=True)
    assert imported.status_code == 200
    assert "Catalog imported: 1 accepted" in html
    assert "Production smoke fixture" in html
    assert "Activate mapping" in html

    with app.app_context():
        source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie_id,
                PlaybackSource.provider == "videotube",
            )
        )
        assert source is not None
        assert source.authorization_status == "catalog_authorized"
        assert source.enabled is False
        source_id = source.id

    activated = authenticated_client.post(
        f"/settings/playback/catalog/sources/{source_id}/enabled",
        data={
            "csrf_token": csrf_from(imported),
            "enabled": "true",
        },
        follow_redirects=True,
    )
    assert activated.status_code == 200
    assert "Videotube mapping activated." in activated.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(PlaybackSource, source_id).enabled is True


def test_streamwish_account_library_sync_is_manual_disabled_and_visible_only_after_activation(
    authenticated_client, app
):
    class FakeStreamWishAccount:
        def list_files(self):
            return [
                {
                    "file_code": "abc123def456",
                    "title": "Arrival [tmdb-329865] 1080p",
                    "fld_id": "movies",
                    "canplay": 1,
                }
            ]

    with app.app_context():
        movie = Movie(
            title="Arrival",
            normalized_title="arrival",
            external_ids={"tmdb_id": "329865"},
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_STREAMWISH_ENABLED=True,
        DRAGON_STREAMWISH_EMBED_URL="https://streamwish.com/e/{asset_id}",
        DRAGON_STREAMWISH_LIBRARY_SYNC_ENABLED=True,
        DRAGON_STREAMWISH_API_KEY="configured-only-in-test",
    )
    app.extensions["dragon_streamwish_account_client"] = FakeStreamWishAccount()
    page = authenticated_client.get("/settings/playback/catalog")
    assert "Ready for a manual account-library sync" in page.get_data(as_text=True)

    synced = authenticated_client.post(
        "/settings/playback/catalog/streamwish/sync",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )
    html = synced.get_data(as_text=True)
    assert synced.status_code == 200
    assert "StreamWish library synced: 1 valid assets cached; 1 mappings await review." in html
    assert "configured-only-in-test" not in html

    with app.app_context():
        source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie_id,
                PlaybackSource.provider == "streamwish",
            )
        )
        assert source is not None
        assert source.source_type == "account_catalog"
        assert source.authorization_status == "account_authorized"
        assert source.enabled is False
        source_id = source.id

    before_activation = authenticated_client.get(f"/movies/{movie_id}").get_data(as_text=True)
    assert "StreamWish · 1080P" not in before_activation
    assert "streamwish.com/e" not in before_activation

    activated = authenticated_client.post(
        f"/settings/playback/catalog/sources/{source_id}/enabled",
        data={"csrf_token": csrf_from(synced), "enabled": "true"},
        follow_redirects=True,
    )
    assert activated.status_code == 200
    detail = authenticated_client.get(f"/movies/{movie_id}").get_data(as_text=True)
    assert "StreamWish · 1080P" in detail
    assert "streamwish.com/e" not in detail
    resolved = authenticated_client.get(
        f"/playback/movie/{movie_id}/sources/{source_id}/embed"
    )
    assert resolved.status_code == 200
    assert resolved.get_json()["source"]["url"] == "https://streamwish.com/e/abc123def456"


def test_mixdrop_account_library_sync_is_manual_disabled_and_visible_only_after_activation(
    authenticated_client, app
):
    class FakeMixDropAccount:
        def list_files(self):
            return [
                {
                    "fileref": "mixdrop123",
                    "title": "Arrival [tmdb-329865] 1080p",
                    "_folder_id": "movies",
                    "isvideo": True,
                    "status": "OK",
                    "deleted": False,
                }
            ]

    with app.app_context():
        movie = Movie(
            title="Arrival",
            normalized_title="arrival",
            external_ids={"tmdb_id": "329865"},
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MIXDROP_ENABLED=True,
        DRAGON_MIXDROP_EMBED_URL="https://mixdrop.ag/e/{asset_id}",
        DRAGON_MIXDROP_LIBRARY_SYNC_ENABLED=True,
        DRAGON_MIXDROP_API_EMAIL="configured@example.test",
        DRAGON_MIXDROP_API_KEY="configured-only-in-test",
    )
    app.extensions["dragon_mixdrop_account_client"] = FakeMixDropAccount()
    page = authenticated_client.get("/settings/playback/catalog")
    assert "MixDrop library sync" in page.get_data(as_text=True)
    assert "Ready for a manual account-library sync" in page.get_data(as_text=True)

    synced = authenticated_client.post(
        "/settings/playback/catalog/mixdrop/sync",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )
    html = synced.get_data(as_text=True)
    assert synced.status_code == 200
    assert "MixDrop library synced: 1 valid assets cached; 1 mappings await review." in html
    assert "configured-only-in-test" not in html

    with app.app_context():
        source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie_id,
                PlaybackSource.provider == "mixdrop",
            )
        )
        assert source is not None
        assert source.source_type == "account_catalog"
        assert source.authorization_status == "account_authorized"
        assert source.enabled is False
        source_id = source.id

    before_activation = authenticated_client.get(f"/movies/{movie_id}").get_data(as_text=True)
    assert "MixDrop · 1080P" not in before_activation
    assert "mixdrop.ag/e" not in before_activation

    activated = authenticated_client.post(
        f"/settings/playback/catalog/sources/{source_id}/enabled",
        data={"csrf_token": csrf_from(synced), "enabled": "true"},
        follow_redirects=True,
    )
    assert activated.status_code == 200
    detail = authenticated_client.get(f"/movies/{movie_id}").get_data(as_text=True)
    assert "MixDrop · 1080P" in detail
    assert "mixdrop.ag/e" not in detail
    resolved = authenticated_client.get(
        f"/playback/movie/{movie_id}/sources/{source_id}/embed"
    )
    assert resolved.status_code == 200
    assert resolved.get_json()["source"]["url"] == "https://mixdrop.ag/e/mixdrop123"


def test_streamtape_account_library_sync_is_manual_disabled_and_visible_only_after_activation(
    authenticated_client, app
):
    class FakeStreamTapeAccount:
        def list_files(self):
            return [
                {
                    "linkid": "streamtape123",
                    "name": "Arrival [tmdb-329865] 1080p",
                    "_folder_id": "movies",
                    "convert": "converted",
                }
            ]

    with app.app_context():
        movie = Movie(
            title="Arrival",
            normalized_title="arrival",
            external_ids={"tmdb_id": "329865"},
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_STREAMTAPE_ENABLED=True,
        DRAGON_STREAMTAPE_EMBED_URL="https://streamtape.com/e/{asset_id}",
        DRAGON_STREAMTAPE_LIBRARY_SYNC_ENABLED=True,
        DRAGON_STREAMTAPE_API_LOGIN="configured-login",
        DRAGON_STREAMTAPE_API_KEY="configured-only-in-test",
    )
    app.extensions["dragon_streamtape_account_client"] = FakeStreamTapeAccount()
    page = authenticated_client.get("/settings/playback/catalog")
    assert "StreamTape library sync" in page.get_data(as_text=True)

    synced = authenticated_client.post(
        "/settings/playback/catalog/streamtape/sync",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )
    assert "StreamTape library synced: 1 valid assets cached; 1 mappings await review." in synced.get_data(as_text=True)

    with app.app_context():
        source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie_id,
                PlaybackSource.provider == "streamtape",
            )
        )
        assert source is not None
        assert source.enabled is False
        source_id = source.id

    activated = authenticated_client.post(
        f"/settings/playback/catalog/sources/{source_id}/enabled",
        data={"csrf_token": csrf_from(synced), "enabled": "true"},
        follow_redirects=True,
    )
    assert activated.status_code == 200
    detail = authenticated_client.get(f"/movies/{movie_id}").get_data(as_text=True)
    assert "StreamTape · 1080P" in detail
    resolved = authenticated_client.get(
        f"/playback/movie/{movie_id}/sources/{source_id}/embed"
    )
    assert resolved.get_json()["source"]["url"] == "https://streamtape.com/e/streamtape123"


def test_filelions_account_library_sync_is_manual_disabled_and_visible_only_after_activation(
    authenticated_client, app
):
    class FakeFileLionsAccount:
        def list_files(self):
            return [{"file_code": "filelions123", "title": "Arrival [tmdb-329865] 720p", "canplay": 1}]

    with app.app_context():
        movie = Movie(title="Arrival", normalized_title="arrival", external_ids={"tmdb_id": "329865"})
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_FILELIONS_ENABLED=True,
        DRAGON_FILELIONS_EMBED_URL="https://filelions.to/v/{asset_id}",
        DRAGON_FILELIONS_LIBRARY_SYNC_ENABLED=True,
        DRAGON_FILELIONS_API_KEY="configured-only-in-test",
    )
    app.extensions["dragon_filelions_account_client"] = FakeFileLionsAccount()
    page = authenticated_client.get("/settings/playback/catalog")
    synced = authenticated_client.post(
        "/settings/playback/catalog/filelions/sync",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )
    assert "FileLions library synced: 1 valid assets cached; 1 mappings await review." in synced.get_data(as_text=True)

    with app.app_context():
        source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie_id,
                PlaybackSource.provider == "filelions",
            )
        )
        assert source is not None and source.enabled is False
        source_id = source.id

    activated = authenticated_client.post(
        f"/settings/playback/catalog/sources/{source_id}/enabled",
        data={"csrf_token": csrf_from(synced), "enabled": "true"},
        follow_redirects=True,
    )
    assert activated.status_code == 200
    assert "FileLions / EarnVids · 720P" in authenticated_client.get(
        f"/movies/{movie_id}"
    ).get_data(as_text=True)
    resolved = authenticated_client.get(f"/playback/movie/{movie_id}/sources/{source_id}/embed")
    assert resolved.get_json()["source"]["url"] == "https://filelions.to/v/filelions123"


def test_cinesrc_direct_tmdb_provider_is_not_contacted_until_watch(authenticated_client, app):
    with app.app_context():
        movie = Movie(
            title="Fight Club", normalized_title="fight club", external_ids={"tmdb_id": "550"}
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config.update(DRAGON_PLAYBACK_ENABLED=True, DRAGON_CINESRC_ENABLED=True)
    detail = authenticated_client.get(f"/movies/{movie_id}")

    assert detail.status_code == 200
    assert "CineSrc" in detail.get_data(as_text=True)
    assert "cinesrc.st/embed" not in detail.get_data(as_text=True)
    assert "frame-src 'self' https://cinesrc.st" in detail.headers["Content-Security-Policy"]
    resolved = authenticated_client.get(f"/playback/movie/{movie_id}/providers/cinesrc")
    assert resolved.status_code == 200
    assert resolved.get_json()["source"]["url"] == "https://cinesrc.st/embed/movie/550"
    with app.app_context():
        source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie_id,
                PlaybackSource.provider == "cinesrc",
            )
        )
        assert source is not None
        assert source.source_type == "id_catalog"


def test_cinesrc_uses_exact_tv_episode_scope(authenticated_client, app):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            external_ids={"tmdb_id": "1399", "tmdb_type": "tv"},
            metadata_state={
                "tv_episodes": {
                    "1": [{"season_number": 1, "episode_number": 5, "name": "College"}],
                    "2": [{"season_number": 2, "episode_number": 5, "name": "Big Girls"}],
                }
            },
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config.update(DRAGON_PLAYBACK_ENABLED=True, DRAGON_CINESRC_ENABLED=True)
    episode_page = authenticated_client.get(f"/movies/{movie_id}/seasons/2/episodes/5")
    resolved = authenticated_client.get(
        f"/playback/movie/{movie_id}/providers/cinesrc?season=2&episode=5"
    )

    assert episode_page.status_code == 200
    assert "CineSrc" in episode_page.get_data(as_text=True)
    assert resolved.status_code == 200
    assert resolved.get_json()["source"]["url"] == "https://cinesrc.st/embed/tv/1399?s=2&e=5"
    with app.app_context():
        source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie_id,
                PlaybackSource.provider == "cinesrc",
            )
        )
        assert source is not None
        assert source.scope_key == "s02e05"


def test_videm_direct_tmdb_provider_resolves_movie_and_exact_tv_episode(
    authenticated_client, app
):
    with app.app_context():
        movie = Movie(
            title="VIDEM test title",
            normalized_title="videm test title",
            media_type="tv",
            external_ids={"tmdb_id": "1399", "tmdb_type": "tv"},
            metadata_state={
                "tv_episodes": {
                    "2": [{"season_number": 2, "episode_number": 5, "name": "Episode 5"}]
                }
            },
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config.update(DRAGON_PLAYBACK_ENABLED=True, DRAGON_VIDEM_ENABLED=True)
    detail = authenticated_client.get(f"/movies/{movie_id}/seasons/2/episodes/5")
    resolved = authenticated_client.get(
        f"/playback/movie/{movie_id}/providers/videm?season=2&episode=5"
    )

    assert detail.status_code == 200
    assert "VIDEM" in detail.get_data(as_text=True)
    assert "frame-src 'self' https://videm.xyz" in detail.headers["Content-Security-Policy"]
    assert resolved.status_code == 200
    assert resolved.get_json()["source"]["url"] == "https://videm.xyz/embed/tv/1399/2/5"


@pytest.mark.parametrize(
    ("provider_key", "config_key", "label", "expected_url"),
    (
        (
            "multiembed",
            "DRAGON_MULTIEMBED_ENABLED",
            "MultiEmbed",
            "https://multiembed.mov/?video_id=550&tmdb=1",
        ),
        (
            "multiembed_vip",
            "DRAGON_MULTIEMBED_VIP_ENABLED",
            "MultiEmbed VIP",
            "https://multiembed.mov/directstream.php?video_id=550&tmdb=1",
        ),
    ),
)
def test_multiembed_direct_movie_providers_are_deferred_until_watch(
    authenticated_client, app, provider_key, config_key, label, expected_url
):
    with app.app_context():
        movie = Movie(
            title="Fight Club", normalized_title="fight club", external_ids={"tmdb_id": "550"}
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config.update(DRAGON_PLAYBACK_ENABLED=True, **{config_key: True})
    detail = authenticated_client.get(f"/movies/{movie_id}")

    assert detail.status_code == 200
    assert label in detail.get_data(as_text=True)
    assert "multiembed.mov/?video_id=550&tmdb=1" not in detail.get_data(as_text=True)
    assert "directstream.php?video_id=550&tmdb=1" not in detail.get_data(as_text=True)
    assert "frame-src 'self' https://multiembed.mov" in detail.headers["Content-Security-Policy"]

    resolved = authenticated_client.get(f"/playback/movie/{movie_id}/providers/{provider_key}")
    assert resolved.status_code == 200
    assert resolved.get_json()["source"]["url"] == expected_url


def test_multiembed_direct_tv_provider_uses_exact_episode_scope(authenticated_client, app):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            external_ids={"tmdb_id": "1399", "tmdb_type": "tv"},
            metadata_state={
                "tv_episodes": {
                    "2": [{"season_number": 2, "episode_number": 5, "name": "Big Girls"}]
                }
            },
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    app.config.update(DRAGON_PLAYBACK_ENABLED=True, DRAGON_MULTIEMBED_ENABLED=True)
    episode_page = authenticated_client.get(f"/movies/{movie_id}/seasons/2/episodes/5")
    resolved = authenticated_client.get(
        f"/playback/movie/{movie_id}/providers/multiembed?season=2&episode=5"
    )

    assert episode_page.status_code == 200
    assert "MultiEmbed" in episode_page.get_data(as_text=True)
    assert resolved.status_code == 200
    assert (
        resolved.get_json()["source"]["url"]
        == "https://multiembed.mov/?video_id=1399&tmdb=1&s=2&e=5"
    )


def test_provider_priority_orders_the_generic_embed_selector(authenticated_client, app):
    with app.app_context():
        movie = Movie(
            title="Prioritized Providers",
            normalized_title="prioritized providers",
            external_ids={"imdb_id": "tt2543164"},
        )
        db.session.add(movie)
        db.session.commit()
        PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="videotube",
            provider_asset_id="iuki4kda2u7l",
            label="VideoTube · Arabic Subs",
        )
        PlaybackService.save_provider_preference(
            provider="videotube",
            enabled=True,
            priority=25,
            background_checks=False,
        )
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_VIDSRC_ENABLED=True,
        DRAGON_VIDEOTUBE_ENABLED=True,
        DRAGON_VIDEOTUBE_EMBED_URL="https://down.vidtube.one/embed-{asset_id}.html",
    )

    html = authenticated_client.get(f"/movies/{movie_id}").get_data(as_text=True)

    assert html.index("VideoTube · Arabic Subs") < html.index("Player 1 · VidSrc")
    assert 'value="vidsrc"' not in html.split("VideoTube · Arabic Subs", maxsplit=1)[0]


def test_all_requested_authorized_hosters_are_available_in_player_source(authenticated_client, app):
    providers = (
        ("videotube", "VideoTube"),
        ("updown", "UpDown"),
        ("streamwish", "StreamWish"),
        ("doodstream", "DoodStream"),
        ("filelions", "FileLions / EarnVids"),
        ("ok", "OK.ru"),
        ("streamtape", "StreamTape"),
        ("lulustream", "LuluStream"),
    )
    with app.app_context():
        movie = Movie(title="All hosters", normalized_title="all hosters")
        db.session.add(movie)
        db.session.commit()
        provider_templates = {
            spec.key: spec.default_embed_url_template
            for spec in INDEXED_EMBED_PROVIDER_SPECS
            if spec.key in {key for key, _ in providers}
        }
        provider_assets = {
            "videotube": "iuki4kda2u7l",
            "updown": "updownasset",
            "streamwish": "streamwish12",
            "doodstream": "doodstreamasset",
            "filelions": "filelionsasset",
            "ok": "7593181055685",
            "streamtape": "streamtapeasset",
            "lulustream": "lulustream12",
        }
        source_ids = {}
        for key, label in providers:
            source = PlaybackService.upsert_indexed_embed_source(
                movie_id=movie.id,
                provider=key,
                provider_asset_id=provider_assets[key],
                label=label,
            )
            source_ids[key] = source.id
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        **{
            setting: value
            for key, _ in providers
            for setting, value in (
                (f"DRAGON_{key.upper()}_ENABLED", True),
                (f"DRAGON_{key.upper()}_EMBED_URL", provider_templates[key]),
            )
        },
    )

    detail = authenticated_client.get(f"/movies/{movie_id}")
    listing = authenticated_client.get(f"/playback/movie/{movie_id}/sources")
    settings = authenticated_client.get("/settings/playback")
    streamwish = authenticated_client.get(
        f"/playback/movie/{movie_id}/sources/{source_ids['streamwish']}/embed"
    )

    assert detail.status_code == 200
    assert [item["provider"] for item in listing.get_json()["items"]] == [
        key for key, _ in providers
    ]
    for _, label in providers:
        assert label in detail.get_data(as_text=True)
        assert label in settings.get_data(as_text=True)
    assert streamwish.get_json()["source"]["url"] == ("https://streamwish.com/e/streamwish12")
    csp = detail.headers["Content-Security-Policy"]
    for template in provider_templates.values():
        parsed = urlsplit(template)
        assert f"{parsed.scheme}://{parsed.netloc}" in csp


def test_authorized_indexed_embed_uses_exact_tv_episode_scope(authenticated_client, app):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            external_ids={"tmdb_id": "1399", "tmdb_type": "tv"},
            metadata_state={
                "tv_episodes": {
                    "2": [{"season_number": 2, "episode_number": 5, "name": "Big Girls"}]
                }
            },
        )
        db.session.add(movie)
        db.session.commit()
        source = PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="videotube",
            provider_asset_id="iuki4kda2u7l",
            label="VideoTube · Arabic Subs",
            season=2,
            episode=5,
        )
        movie_id = movie.id
        source_id = source.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_VIDEOTUBE_ENABLED=True,
        DRAGON_VIDEOTUBE_EMBED_URL="https://down.vidtube.one/embed-{asset_id}.html",
    )

    episode_page = authenticated_client.get(f"/movies/{movie_id}/seasons/2/episodes/5")
    wrong_scope = authenticated_client.get(f"/playback/movie/{movie_id}/sources")
    resolved = authenticated_client.get(
        f"/playback/movie/{movie_id}/sources/{source_id}/embed?season=2&episode=5"
    )

    assert "VideoTube · Arabic Subs" in episode_page.get_data(as_text=True)
    assert wrong_scope.status_code == 400
    assert resolved.status_code == 200
    assert resolved.get_json()["source"]["url"].endswith("embed-iuki4kda2u7l.html")


def test_wyzie_key_enables_subtitle_controls_on_movie_detail(authenticated_client, app):
    with app.app_context():
        movie = Movie(title="Wyzie Ready", normalized_title="wyzie ready")
        db.session.add(movie)
        db.session.flush()
        db.session.add(
            PlaybackSource(
                movie_id=movie.id,
                kind="magnet",
                label="FHD magnet",
                locator="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
            )
        )
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MAGNETS_ENABLED=True,
        DRAGON_SUBTITLES_ENABLED=True,
        DRAGON_SUBTITLE_PROVIDER="wyzie",
        DRAGON_WYZIE_API_KEY="private-wyzie-key",
        DRAGON_SUBDL_API_KEY="",
    )

    detail = authenticated_client.get(f"/movies/{movie_id}")
    detail_html = detail.get_data(as_text=True)

    assert "data-subtitle-status" in detail_html
    assert 'data-subtitle-status aria-live="polite" hidden' in detail_html
    assert "Provider settings" not in detail_html
    assert "private-wyzie-key" not in detail_html


def test_subtitles_are_private_ranked_and_delivered_as_webvtt(authenticated_client, app):
    class StubSubtitleProvider:
        downloads = 0

        def search(self, movie, *, languages, season=None, episode=None, episode_title=""):
            assert movie["external_ids"] == {"imdb_id": "tt2543164"}
            assert languages == "ar,en"
            assert season is None
            assert episode is None
            assert episode_title == ""
            return [
                SubtitleCandidate(
                    language="ar",
                    language_name="Arabic",
                    label="Arabic release",
                    path="/subtitle/archive123-456.zip",
                    file_format="srt",
                    member_name="arrival.ar.srt",
                    hearing_impaired=False,
                ),
                SubtitleCandidate(
                    language="en",
                    language_name="English",
                    label="English release",
                    path="/subtitle/archive789-012.zip",
                    file_format="srt",
                    member_name="arrival.en.srt",
                    hearing_impaired=False,
                ),
            ]

        def download(
            self, path, *, file_format, member_name, season=None, episode=None, episode_title=""
        ):
            assert path == "/subtitle/archive123-456.zip"
            assert file_format == "srt"
            assert member_name == "arrival.ar.srt"
            assert season is None
            assert episode is None
            assert episode_title == ""
            self.downloads += 1
            return "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nمرحبا\n".encode()

    provider = StubSubtitleProvider()
    with app.app_context():
        movie = Movie(
            title="Arrival",
            normalized_title="arrival",
            external_ids={"imdb_id": "tt2543164"},
        )
        db.session.add(movie)
        db.session.flush()
        db.session.add(
            PlaybackSource(
                movie_id=movie.id,
                kind="magnet",
                label="FHD magnet",
                locator="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
            )
        )
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MAGNETS_ENABLED=True,
        DRAGON_SUBTITLES_ENABLED=True,
        DRAGON_SUBDL_API_KEY="private-key",
        DRAGON_SUBTITLE_LANGUAGES="ar,en",
    )
    app.extensions["dragon_subtitle_provider"] = provider

    detail = authenticated_client.get(f"/movies/{movie_id}")
    detail_html = detail.get_data(as_text=True)
    assert "data-subtitle-status" in detail_html
    assert 'data-subtitle-status aria-live="polite" hidden' in detail_html
    assert "Provider settings" not in detail_html
    assert "data-subtitle-select" not in detail_html
    assert "private-key" not in detail_html
    assert "dl.subdl.com" not in detail_html

    options = authenticated_client.get(f"/playback/movie/{movie_id}/subtitles")
    assert options.status_code == 200
    items = options.get_json()["items"]
    assert [item["language"] for item in items] == ["ar", "en"]
    assert all("dl.subdl.com" not in item["track_url"] for item in items)

    track_url = items[0]["track_url"]
    track = authenticated_client.get(track_url)
    assert track.status_code == 200
    assert track.mimetype == "text/vtt"
    assert "مرحبا" in track.get_data(as_text=True)
    assert track.headers["Cache-Control"] == "private, max-age=3600"
    authenticated_client.get(track_url)
    assert provider.downloads == 1

    assert authenticated_client.get(f"{track_url}tampered").status_code == 404
    assert app.test_client().get(track_url).status_code == 302


def test_tv_subtitles_follow_selected_season_and_episode(authenticated_client, app):
    class StubSubtitleProvider:
        def search(self, movie, *, languages, season=None, episode=None, episode_title=""):
            assert movie["external_ids"] == {"tmdb_id": "1399", "tmdb_type": "tv"}
            assert languages == "ar,en"
            assert season == 1
            assert episode == 2
            assert episode_title == "46 Long"
            return [
                SubtitleCandidate(
                    language="ar",
                    language_name="Arabic",
                    label="The Sopranos - Season 1",
                    path="/subtitle/archive123-456.zip",
                    file_format="srt",
                    member_name="sopranos.s01e02.ar.srt",
                    hearing_impaired=False,
                    season=1,
                    episode=2,
                    episode_title="46 Long",
                )
            ]

        def download(
            self, path, *, file_format, member_name, season=None, episode=None, episode_title=""
        ):
            assert season == 1
            assert episode == 2
            assert episode_title == "46 Long"
            return "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nمرحبا\n".encode()

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

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MAGNETS_ENABLED=True,
        DRAGON_SUBTITLES_ENABLED=True,
        DRAGON_SUBDL_API_KEY="private-key",
        DRAGON_SUBTITLE_LANGUAGES="ar,en",
    )
    app.extensions["dragon_subtitle_provider"] = StubSubtitleProvider()

    response = authenticated_client.get(
        f"/playback/movie/{movie_id}/subtitles?season=1&episode=2&episode_title=46+Long"
    )

    assert response.status_code == 200
    items = response.get_json()["items"]
    assert len(items) == 1
    assert items[0]["label"] == "The Sopranos - Season 1"
    track = authenticated_client.get(items[0]["track_url"])
    assert track.status_code == 200


def test_local_magnet_player_is_click_gated_and_keeps_locator_server_side(
    authenticated_client, app
):
    class StubRuntime:
        def start(self, **values):
            assert values["movie_id"] == movie_id
            assert values["source_id"] == source_id
            assert values["magnet"].startswith("magnet:?")
            assert values["torrent_url"] == "https://yts.bz/example.torrent"
            assert values["user_id"]
            assert values["origin"] == "http://localhost"
            assert values["season"] == 1
            assert values["episode"] == 1
            return {
                "id": "play_test",
                "state": "ready",
                "message": "Direct stream ready",
                "file_name": "movie.mp4",
                "stream_url": "http://127.0.0.1:54321/dragon-stream/secret/hash/movie.mp4",
                "stream_kind": "direct",
                "buffer_percent": 50,
                "file_progress": 0.1,
                "downloaded_bytes": 100,
                "peers": 2,
                "download_speed": 1024,
                "cache_hit": True,
                "startup_timings": {"metadata_ms": 10},
                "complete": False,
            }

    locator = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
    with app.app_context():
        movie = Movie(title="Local Player", normalized_title="local player")
        db.session.add(movie)
        db.session.flush()
        source = PlaybackSource(
            movie_id=movie.id,
            kind="magnet",
            label="FHD magnet",
            locator=locator,
            metadata_json={"season": 1, "episode": 1, "season_pack": True},
        )
        db.session.add(source)
        db.session.add(
            PlaybackSource(
                movie_id=movie.id,
                kind="torrent",
                label="FHD torrent",
                locator="https://yts.bz/example.torrent",
            )
        )
        db.session.commit()
        movie_id = movie.id
        source_id = source.id

    app.config["DRAGON_PLAYBACK_ENABLED"] = True
    app.config["DRAGON_MAGNETS_ENABLED"] = True
    app.extensions["dragon_magnet_playback_manager"] = StubRuntime()

    detail = authenticated_client.get(f"/movies/{movie_id}")
    html = detail.get_data(as_text=True)
    assert "Local · FHD" in html
    assert locator not in html
    assert "http://127.0.0.1:" not in html
    assert "media-src 'self' http://127.0.0.1:*" in detail.headers["Content-Security-Policy"]

    response = authenticated_client.post(
        f"/playback/movie/{movie_id}/local",
        json={"source_id": source_id},
        headers={"X-CSRFToken": csrf_from(detail)},
    )
    assert response.status_code == 202
    payload = response.get_json()
    assert payload["session"]["id"] == "play_test"
    assert payload["stream_url"].startswith("http://127.0.0.1:54321/dragon-stream/")
    assert payload["session"]["stream_kind"] == "direct"
    assert payload["transcode_url"].endswith("/playback/runtime/play_test/transcode")
    assert authenticated_client.get("/playback/runtime/play_test/stream").status_code == 404


def test_season_pack_player_exposes_episode_controls_and_payload_overrides(
    authenticated_client, app
):
    class StubRuntime:
        def start(self, **values):
            assert values["season"] == 1
            assert values["episode"] == 5
            return {
                "id": "play_pack",
                "state": "ready",
                "message": "Direct stream ready",
                "file_name": "episode.mp4",
                "stream_url": "http://127.0.0.1:54321/dragon-stream/secret/hash/episode.mp4",
                "stream_kind": "direct",
                "buffer_percent": 50,
                "file_progress": 0.1,
                "downloaded_bytes": 100,
                "peers": 2,
                "download_speed": 1024,
                "cache_hit": True,
                "startup_timings": {"metadata_ms": 10},
                "complete": False,
            }

    with app.app_context():
        movie = Movie(
            title="Pack Show",
            normalized_title="pack show",
            media_type="tv",
            external_ids={"tmdb_id": "1399", "tmdb_type": "tv"},
            metadata_state={
                "tv_total_seasons": 1,
                "tv_total_episodes": 1,
                "tv_seasons": [
                    {"season_number": 1, "name": "Season 1", "episode_count": 1, "poster_url": ""}
                ],
                "tv_episodes": {
                    "1": [
                        {
                            "season_number": 1,
                            "episode_number": 5,
                            "name": "College",
                            "overview": "",
                            "still_url": "",
                            "runtime_minutes": 55,
                        }
                    ]
                },
            },
        )
        db.session.add(movie)
        db.session.flush()
        source = PlaybackSource(
            movie_id=movie.id,
            kind="magnet",
            label="S01 season pack Jackett magnet",
            locator="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
            season=1,
            episode=5,
            source_role="season_pack_fallback",
            metadata_json={
                "season_pack": True,
                "season": 1,
                "episode": 5,
                "release_mode": "season_pack",
            },
            selected=True,
        )
        db.session.add(source)
        db.session.commit()
        movie_id = movie.id
        source_id = source.id

    app.config["DRAGON_PLAYBACK_ENABLED"] = True
    app.config["DRAGON_MAGNETS_ENABLED"] = True
    app.extensions["dragon_magnet_playback_manager"] = StubRuntime()

    detail = authenticated_client.get(f"/movies/{movie_id}")
    html = detail.get_data(as_text=True)
    assert "Season browser" in html
    assert 'data-source-season-pack="true"' not in html

    episode_page = authenticated_client.get(f"/movies/{movie_id}/seasons/1/episodes/5")
    episode_html = episode_page.get_data(as_text=True)
    assert 'data-source-season-pack="true"' in episode_html
    assert 'data-source-season="1"' in episode_html

    response = authenticated_client.post(
        f"/playback/movie/{movie_id}/local",
        json={"source_id": source_id, "season": 1, "episode": 5},
        headers={"X-CSRFToken": csrf_from(episode_page)},
    )

    assert response.status_code == 202
    assert response.get_json()["session"]["id"] == "play_pack"


def test_local_transcode_route_uses_private_loopback_stream_safely(
    authenticated_client, app, monkeypatch
):
    class StubRuntime:
        def status(self, session_id: str, *, user_id: str):
            assert session_id == "play_test"
            assert user_id
            return {
                "id": session_id,
                "state": "ready",
                "message": "Transcode required",
                "file_name": "episode.mkv",
                "stream_url": "http://127.0.0.1:54321/dragon-stream/secret/hash/episode.mkv",
                "stream_kind": "transcode",
                "head_ready": True,
                "buffer_percent": 25,
                "file_progress": 0.05,
                "downloaded_bytes": 100,
                "total_bytes": 1000,
                "peers": 1,
                "download_speed": 512,
                "cache_hit": False,
                "startup_timings": {},
                "complete": False,
            }

        def transcode_path(self, session_id: str, *, user_id: str):
            return None

        def fail(self, session_id: str, *, user_id: str, message: str):
            raise AssertionError(f"Transcode unexpectedly failed: {message}")

    called = {}

    def fake_transcode(
        url: str,
        *,
        allow_private: bool = False,
        input_headers=None,
        start_seconds=None,
        on_failure=None,
    ):
        called["url"] = url
        called["allow_private"] = allow_private
        called["input_headers"] = dict(input_headers or {})
        called["start_seconds"] = start_seconds
        from flask import Response

        return Response(b"mp4-bytes", content_type="video/mp4")

    app.config["DRAGON_PLAYBACK_ENABLED"] = True
    app.config["DRAGON_MAGNETS_ENABLED"] = True
    app.extensions["dragon_magnet_playback_manager"] = StubRuntime()
    monkeypatch.setattr("app.playback.routes.transcode_stream", fake_transcode)

    response = authenticated_client.get("/playback/runtime/play_test/transcode")
    assert response.status_code == 200
    assert response.mimetype == "video/mp4"
    assert called["url"].endswith("/dragon-stream/secret/hash/episode.mkv")
    assert called["allow_private"] is True
    assert called["input_headers"]["Origin"] == "http://localhost"
    assert called["start_seconds"] is None


def test_local_transcode_route_accepts_start_offset(authenticated_client, app, monkeypatch):
    class StubRuntime:
        def status(self, session_id: str, *, user_id: str):
            assert session_id == "play_test"
            assert user_id
            return {
                "id": session_id,
                "state": "ready",
                "message": "Transcode required",
                "file_name": "episode.mkv",
                "stream_url": "http://127.0.0.1:54321/dragon-stream/secret/hash/episode.mkv",
                "stream_kind": "transcode",
                "buffer_percent": 25,
                "file_progress": 0.05,
                "downloaded_bytes": 100,
                "total_bytes": 1000,
                "peers": 1,
                "download_speed": 512,
                "cache_hit": False,
                "startup_timings": {},
                "complete": False,
            }

        def transcode_path(self, session_id: str, *, user_id: str):
            return None

        def fail(self, session_id: str, *, user_id: str, message: str):
            raise AssertionError(f"Transcode unexpectedly failed: {message}")

    called = {}

    def fake_transcode(
        url: str,
        *,
        allow_private: bool = False,
        input_headers=None,
        start_seconds=None,
        on_failure=None,
    ):
        called["url"] = url
        called["allow_private"] = allow_private
        called["input_headers"] = dict(input_headers or {})
        called["start_seconds"] = start_seconds
        from flask import Response

        return Response(b"mp4-bytes", content_type="video/mp4")

    app.config["DRAGON_PLAYBACK_ENABLED"] = True
    app.config["DRAGON_MAGNETS_ENABLED"] = True
    app.extensions["dragon_magnet_playback_manager"] = StubRuntime()
    monkeypatch.setattr("app.playback.routes.transcode_stream", fake_transcode)

    response = authenticated_client.get("/playback/runtime/play_test/transcode?start=42.5")
    assert response.status_code == 200
    assert called["start_seconds"] == 42.5


def test_completed_local_transcode_bypasses_loopback_http(
    authenticated_client, app, monkeypatch, tmp_path
):
    cached_file = tmp_path / "episode.mp4"
    cached_file.write_bytes(b"cached-video")

    class StubRuntime:
        def status(self, session_id: str, *, user_id: str):
            return {
                "id": session_id,
                "state": "ready",
                "stream_url": "http://127.0.0.1:54321/dragon-stream/episode.mp4",
            }

        def transcode_path(self, session_id: str, *, user_id: str):
            return cached_file

        def fail(self, session_id: str, *, user_id: str, message: str):
            raise AssertionError(f"Transcode unexpectedly failed: {message}")

    called = {}

    def fake_transcode(source, **options):
        called["source"] = source
        called["options"] = options
        from flask import Response

        return Response(b"mp4-bytes", content_type="video/mp4")

    app.config["DRAGON_PLAYBACK_ENABLED"] = True
    app.config["DRAGON_MAGNETS_ENABLED"] = True
    app.extensions["dragon_magnet_playback_manager"] = StubRuntime()
    monkeypatch.setattr("app.playback.routes.transcode_stream", fake_transcode)

    response = authenticated_client.get("/playback/runtime/play_test/transcode")

    assert response.status_code == 200
    assert called["source"] == cached_file
    assert called["options"]["allow_private"] is False
    assert called["options"]["input_headers"] is None
