from datetime import UTC, datetime, timedelta

import pytest

from app.extensions import db
from app.movies.models import Movie
from app.playback.identity import PlaybackIdentity
from app.playback.models import PlaybackSource, ProviderAvailability
from app.playback.providers import (
    IdCatalogEmbedProvider,
    IndexedEmbedProvider,
    IndexedEmbedProviderConfig,
    ProviderProbeResult,
    VidSrcProvider,
    build_provider_registry,
)
from app.playback.services import (
    DEFAULT_PROVIDER_PRIORITIES,
    PlaybackService,
    ProviderAvailabilityService,
)
from app.shared.time import utc_now


def test_vidsrc_provider_resolves_movie_with_imdb_identity():
    provider = VidSrcProvider(base_url="https://vidsrc-embed.ru/embed")

    resolved = provider.resolve(
        PlaybackIdentity(
            movie_id="mov_1",
            imdb_id="tt2543164",
            media_type="movie",
            title="Arrival",
        )
    )

    assert resolved.response_item() == {
        "provider": "vidsrc",
        "label": "VidSrc",
        "url": "https://vidsrc-embed.ru/embed/tt2543164",
        "match": "imdb",
    }
    assert resolved.provider_asset_id == "tt2543164"
    assert resolved.playback_mode == "embed"


def test_vidsrc_provider_resolves_exact_tv_episode_with_tmdb_identity():
    provider = VidSrcProvider(base_url="https://vidsrc-embed.ru/embed")

    resolved = provider.resolve(
        PlaybackIdentity(
            movie_id="mov_1",
            tmdb_id="1399",
            media_type="tv",
            season=2,
            episode=5,
        )
    )

    assert resolved.url == "https://vidsrc-embed.ru/embed/tv/1399/2-5"
    assert resolved.match == "tmdb"


def test_vidsrc_provider_rejects_unscoped_tv_identity():
    provider = VidSrcProvider(base_url="https://vidsrc-embed.ru/embed")

    with pytest.raises(ValueError, match="season and an episode"):
        provider.resolve(PlaybackIdentity(movie_id="mov_1", imdb_id="tt0944947", media_type="tv"))


@pytest.mark.parametrize(
    ("key", "movie_url", "episode_url"),
    (
        ("cinesrc", "https://cinesrc.st/embed/movie/550", "https://cinesrc.st/embed/tv/1399?s=1&e=5"),
        ("vidcore", "https://vidcore.org/embed/movie/550", "https://vidcore.org/embed/tv/1399/1/5"),
        ("vidzee", "https://player.vidzee.wtf/embed/movie/550", "https://player.vidzee.wtf/embed/tv/1399/1/5"),
        ("videm", "https://videm.xyz/embed/movie/550", "https://videm.xyz/embed/tv/1399/1/5"),
        ("multiembed", "https://multiembed.mov/?video_id=550&tmdb=1", "https://multiembed.mov/?video_id=1399&tmdb=1&s=1&e=5"),
        ("multiembed_vip", "https://multiembed.mov/directstream.php?video_id=550&tmdb=1", "https://multiembed.mov/directstream.php?video_id=1399&tmdb=1&s=1&e=5"),
    ),
)
def test_direct_id_catalog_provider_resolves_tmdb_movie_and_exact_tv_episode(
    key, movie_url, episode_url
):
    provider = IdCatalogEmbedProvider(key)

    movie = provider.resolve(PlaybackIdentity(movie_id="mov_1", tmdb_id="550", media_type="movie"))
    episode = provider.resolve(
        PlaybackIdentity(movie_id="mov_1", tmdb_id="1399", media_type="tv", season=1, episode=5)
    )

    assert movie.url == movie_url
    assert movie.provider_asset_id == "550"
    assert episode.url == episode_url
    with pytest.raises(ValueError, match="TMDb ID"):
        provider.resolve(PlaybackIdentity(movie_id="mov_1", imdb_id="tt0137523"))


def test_provider_registry_exposes_vidsrc_as_the_only_v0_provider():
    registry = build_provider_registry(vidsrc_embed_url="https://vidsrc-embed.ru/embed")

    assert registry.get("vidsrc") is not None
    assert registry.get("videotube") is None


def test_provider_registry_enables_cinesrc_as_a_direct_identity_provider():
    registry = build_provider_registry(
        vidsrc_embed_url="https://vidsrc-embed.ru/embed",
        cinesrc_enabled=True,
        vidcore_enabled=True,
        vidzee_enabled=True,
        videm_enabled=True,
        multiembed_enabled=True,
        multiembed_vip_enabled=True,
    )

    assert registry.keys() >= {
        "cinesrc",
        "vidcore",
        "vidzee",
        "videm",
        "multiembed",
        "multiembed_vip",
    }


def test_provider_registry_enables_videotube_only_with_an_authorized_endpoint():
    registry = build_provider_registry(
        vidsrc_embed_url="https://vidsrc-embed.ru/embed",
        videotube_enabled=True,
        videotube_embed_url="https://down.vidtube.one/embed-{asset_id}.html",
    )

    assert registry.get("videotube") is not None
    with pytest.raises(ValueError, match="embed URL"):
        build_provider_registry(
            vidsrc_embed_url="https://vidsrc-embed.ru/embed",
            videotube_enabled=True,
        )


def test_provider_registry_reuses_the_indexed_contract_for_every_requested_hoster():
    registry = build_provider_registry(
        vidsrc_embed_url="https://vidsrc-embed.ru/embed",
        updown_enabled=True,
        updown_embed_url="https://updown.icu/embed-{asset_id}-1280x640.html",
        streamwish_enabled=True,
        streamwish_embed_url="https://streamwish.com/e/{asset_id}",
        doodstream_enabled=True,
        doodstream_embed_url="https://dood.to/e/{asset_id}",
        filelions_enabled=True,
        filelions_embed_url="https://filelions.to/v/{asset_id}",
        ok_enabled=True,
        ok_embed_url="https://ok.ru/videoembed/{asset_id}",
        streamtape_enabled=True,
        streamtape_embed_url="https://streamtape.com/e/{asset_id}",
        lulustream_enabled=True,
        lulustream_embed_url="https://lulustream.com/e/{asset_id}",
    )

    requested_hosters = (
        "updown",
        "streamwish",
        "doodstream",
        "filelions",
        "ok",
        "streamtape",
        "lulustream",
    )
    asset_ids = {
        "updown": "updownasset",
        "streamwish": "streamwish12",
        "doodstream": "doodstreamasset",
        "filelions": "filelionsasset",
        "ok": "7593181055685",
        "streamtape": "streamtapeasset",
        "lulustream": "lulustream12",
    }
    for key in requested_hosters:
        resolved = registry.require(key).resolve(
            PlaybackIdentity(movie_id="mov_1"),
            source=type("Source", (), {"provider_asset_id": asset_ids[key]})(),
        )
        assert asset_ids[key] in resolved.url


def test_indexed_embed_provider_uses_only_valid_native_asset_ids():
    provider = IndexedEmbedProvider(
        IndexedEmbedProviderConfig(
            key="videotube",
            embed_url_template="https://down.vidtube.one/embed-{asset_id}.html",
        )
    )
    source = type("Source", (), {"provider_asset_id": "iuki4kda2u7l"})()

    resolved = provider.resolve(PlaybackIdentity(movie_id="mov_1"), source=source)

    assert resolved.url == "https://down.vidtube.one/embed-iuki4kda2u7l.html"
    with pytest.raises(ValueError, match="asset ID"):
        provider.resolve(
            PlaybackIdentity(movie_id="mov_1"),
            source=type("Source", (), {"provider_asset_id": "../../unsafe"})(),
        )


def test_provider_metadata_renders_indexed_templates_exactly():
    registry = build_provider_registry(
        vidsrc_embed_url="https://vidsrc-embed.ru/embed",
        videotube_enabled=True,
        videotube_embed_url="https://down.vidtube.one/embed-{asset_id}.html",
        updown_enabled=True,
        updown_embed_url="https://updown.icu/embed-{asset_id}-1280x640.html",
        ok_enabled=True,
        ok_embed_url="https://ok.ru/videoembed/{asset_id}",
    )
    identity = PlaybackIdentity(movie_id="mov_1")

    assert registry.require("videotube").resolve(
        identity, source=type("Source", (), {"provider_asset_id": "videoasset"})()
    ).url == "https://down.vidtube.one/embed-videoasset.html"
    assert registry.require("updown").resolve(
        identity, source=type("Source", (), {"provider_asset_id": "updownasset"})()
    ).url == "https://updown.icu/embed-updownasset-1280x640.html"
    assert registry.require("ok").resolve(
        identity, source=type("Source", (), {"provider_asset_id": "7593181055685"})()
    ).url == "https://ok.ru/videoembed/7593181055685"
    assert DEFAULT_PROVIDER_PRIORITIES == {
        "videotube": 10,
        "cinesrc": 15,
        "vidcore": 16,
        "vidzee": 17,
        "videm": 18,
        "multiembed": 19,
        "multiembed_vip": 20,
        "updown": 20,
        "streamwish": 30,
        "mixdrop": 35,
        "doodstream": 40,
        "filelions": 50,
        "ok": 60,
        "streamtape": 70,
        "lulustream": 80,
        "uqload": 90,
        "vidsrc": 100,
    }


@pytest.mark.parametrize(
    "embed_template",
    [
        "https://down.vidtube.one/embed-video.html",
        "https://down.vidtube.one/embed-{asset_id}-{unknown}.html",
        "https://not-allowlisted.example/embed-{asset_id}.html",
    ],
)
def test_indexed_embed_templates_reject_missing_unknown_or_unallowlisted_forms(embed_template):
    with pytest.raises(ValueError):
        IndexedEmbedProvider(
            IndexedEmbedProviderConfig(key="videotube", embed_url_template=embed_template)
        )


@pytest.mark.parametrize(
    "embed_template",
    [
        "https://user:pass@down.vidtube.one/embed-{asset_id}.html",
        "https://down.vidtube.one:bad/embed-{asset_id}.html",
    ],
)
def test_embed_providers_reject_credentialed_or_invalid_port_templates(embed_template):
    with pytest.raises(ValueError, match="plain HTTPS embed base URL"):
        VidSrcProvider(base_url=embed_template)
    with pytest.raises(ValueError, match="plain HTTPS embed URL template"):
        IndexedEmbedProvider(
            IndexedEmbedProviderConfig(
                key="videotube",
                embed_url_template=embed_template,
            )
        )


def test_vidsrc_upsert_keeps_one_catalog_source_when_identity_is_enriched(app):
    with app.app_context():
        movie = Movie(title="Arrival", normalized_title="arrival")
        db.session.add(movie)
        db.session.commit()
        provider = VidSrcProvider(base_url="https://vidsrc-embed.ru/embed")

        tmdb_identity = PlaybackIdentity(
            movie_id=movie.id,
            tmdb_id="329865",
            media_type="movie",
        )
        first = PlaybackService.upsert_resolved_source(
            identity=tmdb_identity,
            resolved=provider.resolve(tmdb_identity),
        )

        imdb_identity = PlaybackIdentity(
            movie_id=movie.id,
            tmdb_id="329865",
            imdb_id="tt2543164",
            media_type="movie",
        )
        second = PlaybackService.upsert_resolved_source(
            identity=imdb_identity,
            resolved=provider.resolve(imdb_identity),
        )

        sources = list(
            db.session.scalars(
                db.select(PlaybackSource).where(
                    PlaybackSource.movie_id == movie.id,
                    PlaybackSource.provider == "vidsrc",
                )
            )
        )
        assert second.id == first.id
        assert len(sources) == 1
        assert sources[0].provider_asset_id == "tt2543164"


def test_provider_availability_keeps_one_current_row_and_backs_off(app):
    with app.app_context():
        movie = Movie(title="Arrival", normalized_title="arrival")
        source = PlaybackSource(
            movie_id="placeholder",
            kind="embed",
            label="VidSrc",
            locator="tt2543164",
            provider="vidsrc",
            source_type="id_catalog",
            provider_asset_id="tt2543164",
        )
        db.session.add(movie)
        db.session.flush()
        source.movie_id = movie.id
        db.session.add(source)
        db.session.commit()
        started = datetime(2026, 8, 9, tzinfo=UTC)

        unknown = ProviderAvailabilityService.record(
            source,
            ProviderProbeResult(status="UNKNOWN"),
            now=started,
        )
        assert unknown.expires_at.replace(tzinfo=UTC) == started + timedelta(minutes=5)
        assert unknown.failure_count == 0

        unavailable = ProviderAvailabilityService.record(
            source,
            ProviderProbeResult(status="UNAVAILABLE", failure_reason="Timed out"),
            now=started + timedelta(minutes=6),
        )
        assert unavailable.id == unknown.id
        assert unavailable.failure_count == 1
        assert unavailable.expires_at.replace(tzinfo=UTC) == started + timedelta(minutes=11)

        still_unknown = ProviderAvailabilityService.record(
            source,
            ProviderProbeResult(status="UNKNOWN"),
            now=started + timedelta(minutes=12),
        )
        assert still_unknown.failure_count == 1
        assert still_unknown.expires_at.replace(tzinfo=UTC) == started + timedelta(minutes=17)

        available = ProviderAvailabilityService.record(
            source,
            ProviderProbeResult(status="AVAILABLE", probe_level="EMBED_READY"),
            now=started + timedelta(minutes=18),
        )
        assert available.failure_count == 0
        assert available.last_success_at.replace(tzinfo=UTC) == started + timedelta(minutes=18)
        assert (
            db.session.scalar(
                db.select(ProviderAvailability).where(
                    ProviderAvailability.playback_source_id == source.id
                )
            ).id
            == unknown.id
        )


def test_provider_availability_rejects_an_undefined_probe_level(app):
    with app.app_context():
        movie = Movie(title="Arrival", normalized_title="arrival")
        db.session.add(movie)
        db.session.flush()
        source = PlaybackSource(
            movie_id=movie.id,
            kind="embed",
            label="VideoTube",
            locator="asset-1",
            provider="videotube",
            source_type="known_embed",
            provider_asset_id="asset-1",
        )
        db.session.add(source)
        db.session.commit()

        with pytest.raises(ValueError, match="probe level"):
            ProviderAvailabilityService.record(
                source,
                ProviderProbeResult(status="AVAILABLE", probe_level="PLAYING"),
            )


def test_stale_availability_is_revalidated_once_and_fresh_cache_is_reused(app):
    class StubProvider:
        key = "stub"
        calls = 0

        def probe(self, identity, *, source=None):
            self.calls += 1
            assert identity.movie_id == movie_id
            assert source.provider_asset_id == "asset-1"
            return ProviderProbeResult(status="AVAILABLE", probe_level="EMBED_READY")

    with app.app_context():
        movie = Movie(title="Arrival", normalized_title="arrival")
        db.session.add(movie)
        db.session.flush()
        movie_id = movie.id
        source = PlaybackSource(
            movie_id=movie_id,
            kind="embed",
            label="Stub",
            locator="asset-1",
            provider="stub",
            source_type="known_embed",
            provider_asset_id="asset-1",
        )
        db.session.add(source)
        db.session.commit()
        identity = PlaybackIdentity(movie_id=movie_id, imdb_id="tt2543164")
        provider = StubProvider()
        now = datetime(2026, 8, 9, tzinfo=UTC)

        first = ProviderAvailabilityService.revalidate_if_stale(
            source,
            identity=identity,
            provider=provider,
            now=now,
        )
        second = ProviderAvailabilityService.revalidate_if_stale(
            source,
            identity=identity,
            provider=provider,
            now=now + timedelta(minutes=1),
        )

        assert provider.calls == 1
        assert second.id == first.id


def test_manual_indexed_embed_mapping_is_episode_scoped_and_idempotent(app):
    with app.app_context():
        movie = Movie(title="The Sopranos", normalized_title="the sopranos", media_type="tv")
        db.session.add(movie)
        db.session.commit()

        first = PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="videotube",
            provider_asset_id="iuki4kda2u7l",
            label="VideoTube · Arabic Subs",
            season=1,
            episode=5,
            language="original",
            subtitle_languages=["ar"],
        )
        second = PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="videotube",
            provider_asset_id="iuki4kda2u7l",
            label="VideoTube · Arabic Subs",
            season=1,
            episode=5,
            language="original",
            subtitle_languages=["ar"],
        )

        assert first.id == second.id
        assert second.scope_key == "s01e05"
        assert second.source_type == "known_embed"
        assert second.authorization_status == "manual_authorized"


def test_source_index_hides_only_fresh_unavailable_embed_sources(app):
    with app.app_context():
        movie = Movie(title="Arrival", normalized_title="arrival")
        db.session.add(movie)
        db.session.commit()
        source = PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="videotube",
            provider_asset_id="iuki4kda2u7l",
            label="VideoTube",
        )

        ProviderAvailabilityService.record(
            source,
            ProviderProbeResult(status="UNAVAILABLE"),
        )
        assert PlaybackService.indexed_embed_sources(movie.id) == []

        availability = ProviderAvailabilityService.current(source.id)
        availability.expires_at = utc_now() - timedelta(seconds=1)
        db.session.commit()

        listed_ids = [item["id"] for item in PlaybackService.indexed_embed_sources(movie.id)]
        assert listed_ids == [source.id]


def test_source_priority_override_beats_its_provider_default(app):
    with app.app_context():
        movie = Movie(title="Priority override", normalized_title="priority override")
        db.session.add(movie)
        db.session.commit()
        videotube = PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="videotube",
            provider_asset_id="video-asset",
            label="VideoTube",
        )
        updown = PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="updown",
            provider_asset_id="updown-asset",
            label="UpDown",
        )
        videotube.priority_override = 1
        db.session.commit()

        items = PlaybackService.indexed_embed_sources(
            movie.id,
            provider_priorities={"videotube": 100, "updown": 25},
        )

        assert [item["id"] for item in items] == [videotube.id, updown.id]


def test_requested_hosters_use_videotube_first_by_default(app):
    with app.app_context():
        preferences = PlaybackService.provider_preferences(
            {"videotube", "updown", "streamwish", "vidsrc"}
        )

        assert preferences["videotube"]["priority"] == 10
        assert preferences["updown"]["priority"] == 20
        assert preferences["streamwish"]["priority"] == 30
        assert preferences["vidsrc"]["priority"] == 100
