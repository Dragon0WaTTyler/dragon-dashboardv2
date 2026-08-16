from pathlib import Path

from app.extensions import db
from app.movies.models import Movie
from app.playback.catalog import CatalogImportService, parse_catalog_csv, parse_catalog_json
from app.playback.models import ImportRow, PlaybackSource
from app.playback.services import PlaybackService


def _movie(*, title="Arrival", media_type="movie", tmdb_id="329865", metadata_state=None):
    movie = Movie(
        title=title,
        normalized_title=title.casefold(),
        media_type=media_type,
        year=2025,
        external_ids={"tmdb_id": tmdb_id, "tmdb_type": media_type},
        metadata_state=metadata_state or {},
    )
    db.session.add(movie)
    db.session.commit()
    return movie


def _rows(batch):
    return list(
        db.session.scalars(
            db.select(ImportRow)
            .where(ImportRow.batch_id == batch.id)
            .order_by(ImportRow.row_number)
        )
    )


def test_authorized_catalog_sample_has_the_supported_json_shape():
    sample = Path(__file__).parents[2] / "docs" / "playback" / "authorized-catalog.sample.json"

    rows = parse_catalog_json(sample.read_bytes())

    assert [row["provider_key"] for row in rows] == ["videotube", "updown", "ok"]
    assert rows[2]["media_type"] == "tv"
    assert rows[2]["season"] == rows[2]["episode"] == 1


def test_exact_movie_import_creates_idempotent_playback_source(app):
    with app.app_context():
        movie = _movie(tmdb_id="950387")
        rows = [
            {
                "tmdb_id": "950387",
                "media_type": "movie",
                "provider": "videotube",
                "provider_asset_id": "minecraft-asset",
                "language": "en",
                "subtitle_languages": ["ar", "en"],
                "quality": "1080p",
                "priority_override": 0,
            }
        ]

        first = CatalogImportService.import_rows(rows, import_method="json", source_name="fixture")
        second = CatalogImportService.import_rows(rows, import_method="json", source_name="fixture")

        sources = list(
            db.session.scalars(
                db.select(PlaybackSource).where(
                    PlaybackSource.movie_id == movie.id,
                    PlaybackSource.provider == "videotube",
                )
            )
        )
        assert first.accepted_rows == second.accepted_rows == 1
        assert len(sources) == 1
        assert sources[0].provider_asset_id == "minecraft-asset"
        assert sources[0].authorization_status == "catalog_authorized"
        assert sources[0].enabled is False
        assert sources[0].subtitle_languages == ["ar", "en"]
        assert sources[0].priority_override == 0
        assert sources[0].provenance["origin"] == "catalog_import"


def test_exact_tv_episode_import_is_scoped_and_missing_episode_stays_in_review(app):
    with app.app_context():
        movie = _movie(
            title="The Sopranos",
            media_type="tv",
            tmdb_id="1399",
            metadata_state={
                "tv_episodes": {
                    "1": [{"season_number": 1, "episode_number": 5, "name": "College"}]
                }
            },
        )
        accepted = CatalogImportService.import_rows(
            [
                {
                    "tmdb_id": "1399",
                    "media_type": "tv",
                    "season": 1,
                    "episode": 5,
                    "provider": "updown",
                    "provider_asset_id": "episode-five",
                }
            ],
            import_method="json",
            source_name="fixture",
        )
        review = CatalogImportService.import_rows(
            [
                {
                    "tmdb_id": "1399",
                    "media_type": "tv",
                    "season": 1,
                    "provider": "updown",
                    "provider_asset_id": "missing-episode",
                }
            ],
            import_method="json",
            source_name="fixture",
        )

        source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie.id,
                PlaybackSource.provider == "updown",
            )
        )
        assert accepted.accepted_rows == 1
        assert source.scope_key == "s01e05"
        assert review.review_rows == 1
        assert _rows(review)[0].created_playback_source_id is None


def test_title_and_year_only_are_reviewed_without_publishing(app):
    with app.app_context():
        movie = _movie(title="Weak Match", tmdb_id="42")
        batch = CatalogImportService.import_rows(
            [
                {
                    "title": "Weak Match",
                    "year": 2025,
                    "media_type": "movie",
                    "provider": "videotube",
                    "provider_asset_id": "weak-match",
                }
            ],
            import_method="json",
            source_name="fixture",
        )

        row = _rows(batch)[0]
        assert batch.accepted_rows == 0
        assert batch.review_rows == 1
        assert row.matched_movie_id == movie.id
        assert row.created_playback_source_id is None
        assert PlaybackService.indexed_embed_sources(movie.id) == []


def test_catalog_url_alias_is_normalized_and_unknown_or_invalid_sources_reject(app):
    with app.app_context():
        movie = _movie(tmdb_id="950387")
        batch = CatalogImportService.import_rows(
            [
                {
                    "tmdb_id": "950387",
                    "media_type": "movie",
                    "embed_url": "https://down.vidtube.one/embed-alias-asset.html",
                },
                {
                    "tmdb_id": "950387",
                    "media_type": "movie",
                    "embed_url": "https://unknown.example/embed/nope",
                },
                {
                    "tmdb_id": "950387",
                    "media_type": "movie",
                    "provider": "updown",
                    "provider_asset_id": "../../unsafe",
                },
            ],
            import_method="json",
            source_name="fixture",
        )

        rows = _rows(batch)
        source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie.id,
                PlaybackSource.provider == "videotube",
            )
        )
        assert batch.accepted_rows == 1
        assert batch.rejected_rows == 2
        assert source.provider_asset_id == "alias-asset"
        assert rows[0].raw_data == {
            "tmdb_id": "950387",
            "media_type": "movie",
            "embed_reference_provided": True,
        }
        assert rows[0].raw_reference == "alias-asset"
        assert rows[1].match_status == "rejected"
        assert rows[2].match_status == "rejected"


def test_catalog_okru_alias_imports_as_the_existing_ok_provider_key(app):
    with app.app_context():
        movie = _movie(tmdb_id="950387")
        batch = CatalogImportService.import_rows(
            [
                {
                    "tmdb_id": "950387",
                    "media_type": "movie",
                    "provider": "okru",
                    "provider_asset_id": "7593181055685",
                }
            ],
            import_method="json",
            source_name="fixture",
        )

        source = db.session.scalar(
            db.select(PlaybackSource).where(PlaybackSource.movie_id == movie.id)
        )
        assert batch.accepted_rows == 1
        assert source.provider == "ok"
        assert source.provider_asset_id == "7593181055685"


def test_catalog_import_does_not_touch_vidsrc_or_local_sources(app):
    with app.app_context():
        movie = _movie(tmdb_id="950387")
        vidsrc = PlaybackSource(
            movie_id=movie.id,
            kind="embed",
            label="VidSrc",
            locator="950387",
            provider="vidsrc",
            source_type="id_catalog",
            provider_asset_id="950387",
        )
        local = PlaybackSource(
            movie_id=movie.id,
            kind="magnet",
            label="Local magnet",
            locator="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
        )
        db.session.add_all((vidsrc, local))
        db.session.commit()
        before_local = PlaybackService.player_sources(movie.id)

        batch = CatalogImportService.import_rows(
            [
                {
                    "tmdb_id": "950387",
                    "media_type": "movie",
                    "provider": "vidsrc",
                    "provider_asset_id": "950387",
                }
            ],
            import_method="json",
            source_name="fixture",
        )

        assert batch.rejected_rows == 1
        assert db.session.get(PlaybackSource, vidsrc.id).source_type == "id_catalog"
        assert PlaybackService.player_sources(movie.id) == before_local


def test_catalog_parsers_accept_authorized_json_and_csv_shapes():
    json_rows = parse_catalog_json(
        '[{"tmdb_id":"950387","media_type":"movie","provider":"videotube","provider_asset_id":"asset"}]'
    )
    csv_rows = parse_catalog_csv(
        "tmdb_id,media_type,provider,provider_asset_id\n950387,movie,videotube,asset\n"
    )

    assert json_rows[0]["provider"] == "videotube"
    assert csv_rows[0]["provider_asset_id"] == "asset"
