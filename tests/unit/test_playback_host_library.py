import pytest

from app.extensions import db
from app.movies.models import Movie
from app.playback.host_library import (
    DoodStreamLibrarySyncService,
    FileLionsLibrarySyncService,
    HostLibrarySyncError,
    LuluStreamLibrarySyncService,
    MixDropAccountClient,
    MixDropLibrarySyncService,
    StreamTapeAccountClient,
    StreamTapeLibrarySyncService,
    StreamWishAccountClient,
    StreamWishLibrarySyncService,
)
from app.playback.models import PlaybackSource, ProviderAccountAsset
from app.playback.services import PlaybackService


class FakeStreamWishAccount:
    def __init__(self, files):
        self.files = files
        self.calls = 0

    def list_files(self):
        self.calls += 1
        return list(self.files)


class FakeMixDropAccount(FakeStreamWishAccount):
    pass


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_streamwish_client_paginates_the_account_api_without_following_redirects():
    calls = []
    payloads = iter(
        [
            {"status": 200, "result": {"pages": 2, "files": [{"file_code": "one"}]}},
            {"status": 200, "result": {"pages": 2, "files": [{"file_code": "two"}]}},
        ]
    )

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(next(payloads))

    files = StreamWishAccountClient("secret-key", http_get=fake_get).list_files()

    assert [item["file_code"] for item in files] == ["one", "two"]
    assert [kwargs["params"]["page"] for _, kwargs in calls] == [1, 2]
    assert all(kwargs["allow_redirects"] is False for _, kwargs in calls)
    assert all(kwargs["timeout"] == 15 for _, kwargs in calls)


def test_streamwish_client_rejects_an_invalid_account_response():
    client = StreamWishAccountClient(
        "secret-key",
        http_get=lambda *args, **kwargs: FakeResponse({"status": 403, "result": {}}),
    )

    with pytest.raises(HostLibrarySyncError, match="rejected"):
        client.list_files()


def test_mixdrop_client_lists_nested_account_folders_without_following_redirects():
    calls = []
    payloads = iter(
        [
            {
                "success": True,
                "pages": 1,
                "result": {"folders": [{"id": "5"}], "files": [{"fileref": "root"}]},
            },
            {
                "success": True,
                "pages": 1,
                "result": {"folders": [], "files": [{"fileref": "nested"}]},
            },
        ]
    )

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(next(payloads))

    files = MixDropAccountClient(
        "account@example.test",
        "secret-key",
        http_get=fake_get,
        sleep_fn=lambda _: None,
        monotonic_fn=lambda: 1.0,
    ).list_files()

    assert [item["fileref"] for item in files] == ["root", "nested"]
    assert [item["_folder_id"] for item in files] == ["0", "5"]
    assert all(url == "https://api.mixdrop.ag/folderlist" for url, _ in calls)
    assert all(kwargs["allow_redirects"] is False for _, kwargs in calls)
    assert all(kwargs["timeout"] == 15 for _, kwargs in calls)
    assert all("email" in kwargs["params"] and "key" in kwargs["params"] for _, kwargs in calls)


def test_streamtape_client_lists_nested_account_folders_without_following_redirects():
    calls = []
    payloads = iter(
        [
            {"status": 200, "result": {"folders": [{"id": "folder-a"}], "files": [{"linkid": "root"}]}},
            {"status": 200, "result": {"folders": [], "files": [{"linkid": "nested"}]}},
        ]
    )

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(next(payloads))

    files = StreamTapeAccountClient("login", "secret-key", http_get=fake_get).list_files()

    assert [item["linkid"] for item in files] == ["root", "nested"]
    assert [item["_folder_id"] for item in files] == ["", "folder-a"]
    assert all(kwargs["allow_redirects"] is False for _, kwargs in calls)
    assert all(kwargs["timeout"] == 15 for _, kwargs in calls)
    assert "folder" not in calls[0][1]["params"]
    assert calls[1][1]["params"]["folder"] == "folder-a"


def _movie(*, title, media_type, tmdb_id, metadata_state=None):
    movie = Movie(
        title=title,
        normalized_title=title.casefold(),
        media_type=media_type,
        external_ids={"tmdb_id": tmdb_id, "tmdb_type": media_type},
        metadata_state=metadata_state or {},
    )
    db.session.add(movie)
    db.session.commit()
    return movie


def test_streamwish_library_sync_caches_account_assets_and_creates_disabled_exact_mappings(app):
    with app.app_context():
        movie = _movie(title="Interstellar", media_type="movie", tmdb_id="157336")
        series = _movie(
            title="Breaking Bad",
            media_type="tv",
            tmdb_id="1396",
            metadata_state={
                "tv_episodes": {"1": [{"season_number": 1, "episode_number": 5}]}
            },
        )
        account = FakeStreamWishAccount(
            [
                {
                    "file_code": "abc123def456",
                    "title": "Interstellar 2014 [tmdb-157336] 1080p",
                    "fld_id": "movies",
                    "canplay": 1,
                    "uploaded": "2026-08-11 12:00:00",
                },
                {
                    "file_code": "def456ghi789",
                    "title": "Breaking Bad S01E05 [tmdb-1396] 720p",
                    "fld_id": "shows",
                    "canplay": "true",
                },
                {
                    "file_code": "ghi789jkl012",
                    "title": "A weak filename without identity",
                    "canplay": 1,
                },
                {
                    "file_code": "jkl012mno345",
                    "title": "Interstellar [tmdb-157336] unavailable",
                    "canplay": 0,
                },
            ]
        )

        first = StreamWishLibrarySyncService.sync(account)
        second = StreamWishLibrarySyncService.sync(account)

        sources = list(
            db.session.scalars(
                db.select(PlaybackSource)
                .where(PlaybackSource.provider == "streamwish")
                .order_by(PlaybackSource.provider_asset_id)
            )
        )
        assets = list(
            db.session.scalars(
                db.select(ProviderAccountAsset)
                .where(ProviderAccountAsset.provider == "streamwish")
                .order_by(ProviderAccountAsset.provider_asset_id)
            )
        )

        assert account.calls == 2
        assert first.assets_seen == first.assets_cached == 4
        assert first.batch.accepted_rows == 2
        assert first.batch.review_rows == 2
        assert second.batch.accepted_rows == 2
        assert len(assets) == 4
        assert len(sources) == 2
        assert {source.movie_id for source in sources} == {movie.id, series.id}
        assert {source.scope_key for source in sources} == {"movie", "s01e05"}
        assert all(source.source_type == "account_catalog" for source in sources)
        assert all(source.authorization_status == "account_authorized" for source in sources)
        assert not any(source.enabled for source in sources)
        assert all(source.provenance["origin"] == "account_library_sync" for source in sources)
        assert PlaybackService.indexed_embed_sources(
            movie.id, enabled_providers={"streamwish"}
        ) == []


def test_streamwish_library_sync_never_auto_publishes_title_only_or_unplayable_assets(app):
    with app.app_context():
        movie = _movie(title="Arrival", media_type="movie", tmdb_id="329865")
        account = FakeStreamWishAccount(
            [
                {
                    "file_code": "abc123def456",
                    "title": "Arrival 2016 1080p",
                    "canplay": 1,
                },
                {
                    "file_code": "def456ghi789",
                    "title": "Arrival [tmdb-329865]",
                    "canplay": 0,
                },
            ]
        )

        result = StreamWishLibrarySyncService.sync(account)

        assert result.batch.accepted_rows == 0
        assert result.batch.review_rows == 2
        assert db.session.scalar(
            db.select(PlaybackSource).where(PlaybackSource.movie_id == movie.id)
        ) is None


def test_mixdrop_library_sync_creates_disabled_exact_mappings_only(app):
    with app.app_context():
        movie = _movie(title="Interstellar", media_type="movie", tmdb_id="157336")
        account = FakeMixDropAccount(
            [
                {
                    "fileref": "mixdrop123",
                    "title": "Interstellar [tmdb-157336] 1080p",
                    "_folder_id": "movies",
                    "isvideo": True,
                    "status": "OK",
                    "deleted": False,
                },
                {
                    "fileref": "broken123",
                    "title": "Interstellar [tmdb-157336]",
                    "isvideo": True,
                    "status": "Converting",
                    "deleted": False,
                },
            ]
        )

        first = MixDropLibrarySyncService.sync(account)
        second = MixDropLibrarySyncService.sync(account)
        source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie.id,
                PlaybackSource.provider == "mixdrop",
            )
        )
        assets = list(
            db.session.scalars(
                db.select(ProviderAccountAsset).where(ProviderAccountAsset.provider == "mixdrop")
            )
        )

        assert first.batch.accepted_rows == 1
        assert first.batch.review_rows == 1
        assert second.batch.accepted_rows == 1
        assert source is not None
        assert source.provider_asset_id == "mixdrop123"
        assert source.source_type == "account_catalog"
        assert source.authorization_status == "account_authorized"
        assert source.enabled is False
        assert len(assets) == 2


def test_streamtape_library_sync_creates_disabled_exact_mappings_only(app):
    with app.app_context():
        movie = _movie(title="Arrival", media_type="movie", tmdb_id="329865")
        account = FakeStreamWishAccount(
            [
                {
                    "linkid": "streamtape123",
                    "name": "Arrival [tmdb-329865] 720p",
                    "_folder_id": "movies",
                    "convert": "converted",
                },
                {
                    "linkid": "pending123",
                    "name": "Arrival [tmdb-329865]",
                    "convert": "converting",
                },
            ]
        )

        result = StreamTapeLibrarySyncService.sync(account)
        source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie.id,
                PlaybackSource.provider == "streamtape",
            )
        )

        assert result.batch.accepted_rows == 1
        assert result.batch.review_rows == 1
        assert source is not None
        assert source.provider_asset_id == "streamtape123"
        assert source.enabled is False


def test_filelions_library_sync_creates_disabled_exact_mappings_only(app):
    with app.app_context():
        movie = _movie(title="Arrival", media_type="movie", tmdb_id="329865")
        account = FakeStreamWishAccount(
            [
                {
                    "file_code": "filelions123",
                    "title": "Arrival [tmdb-329865] 720p",
                    "fld_id": "movies",
                    "canplay": 1,
                    "status": "OK",
                }
            ]
        )

        result = FileLionsLibrarySyncService.sync(account)
        source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie.id,
                PlaybackSource.provider == "filelions",
            )
        )

        assert result.batch.accepted_rows == 1
        assert source is not None
        assert source.provider_asset_id == "filelions123"
        assert source.enabled is False


def test_doodstream_library_sync_creates_disabled_exact_mappings_only(app):
    with app.app_context():
        movie = _movie(title="Arrival", media_type="movie", tmdb_id="329865")
        result = DoodStreamLibrarySyncService.sync(
            FakeStreamWishAccount(
                [{"file_code": "dood123", "title": "Arrival [tmdb-329865]", "canplay": 1}]
            )
        )
        source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie.id,
                PlaybackSource.provider == "doodstream",
            )
        )
        assert result.batch.accepted_rows == 1
        assert source is not None and source.enabled is False


def test_lulustream_library_sync_creates_disabled_exact_mappings_only(app):
    with app.app_context():
        movie = _movie(title="Arrival", media_type="movie", tmdb_id="329865")
        result = LuluStreamLibrarySyncService.sync(
            FakeStreamWishAccount(
                [{"file_code": "abc123def456", "title": "Arrival [tmdb-329865]", "canplay": 1}]
            )
        )
        source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie.id,
                PlaybackSource.provider == "lulustream",
            )
        )
        assert result.batch.accepted_rows == 1
        assert source is not None and source.enabled is False
