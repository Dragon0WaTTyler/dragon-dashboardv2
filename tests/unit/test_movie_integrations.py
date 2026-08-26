from app.movies.integrations import (
    JackettReleaseProvider,
    NotionMovieProvider,
    TmdbCatalogProvider,
    _notion_status,
)


class FakeResponse:
    ok = True
    status_code = 200

    def json(self):
        return {
            "Results": [
                {
                    "Title": "Arrival 2016 1080p",
                    "MagnetUri": "magnet:?xt=urn:btih:AAAA&dn=arrival",
                    "Seeders": 18,
                    "Size": 1_500_000_000,
                    "Tracker": "YTS",
                },
                {
                    "Title": "Arrival low seed",
                    "MagnetUri": "magnet:?xt=urn:btih:BBBB&dn=arrival",
                    "Seeders": 4,
                    "Size": 700_000_000,
                    "Tracker": "Example",
                },
                {
                    "Title": "Arrival duplicate",
                    "MagnetUri": "magnet:?xt=urn:btih:AAAA&dn=duplicate",
                    "Seeders": 9,
                    "Size": 1_000_000_000,
                    "Tracker": "Other",
                },
            ]
        }


class FakeSession:
    def __init__(self):
        self.params = None

    def get(self, _url, *, params, headers, timeout):
        self.params = params
        assert headers["Accept"] == "application/json"
        assert timeout == 30
        return FakeResponse()


class JsonResponse:
    ok = True
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class TmdbAliasSession:
    def __init__(self):
        self.calls = []

    def get(self, url, *, params, headers, timeout):
        self.calls.append(url)
        if url.endswith("/alternative_titles"):
            return JsonResponse(
                {
                    "titles": [
                        {"title": "Where Is The Friend's House?"},
                        {"title": "Khane-ye doost kojast?"},
                        {"title": "Khane-ye dust kojast?"},
                    ]
                }
            )
        return JsonResponse(
            {
                "id": 49964,
                "title": "Where Is the Friend's House?",
                "original_title": "خانه‌ی دوست کجاست؟",
                "original_language": "fa",
                "release_date": "1987-01-01",
                "external_ids": {"imdb_id": "tt0093342"},
                "credits": {},
                "genres": [],
            }
        )


class TmdbTrendingSession:
    def __init__(self):
        self.calls = []

    def get(self, url, *, params, headers, timeout):
        self.calls.append((url, params, headers, timeout))
        return JsonResponse(
            {
                "results": [
                    {
                        "id": 603,
                        "title": "The Matrix",
                        "original_title": "The Matrix",
                        "release_date": "1999-03-30",
                        "poster_path": "/matrix.jpg",
                        "backdrop_path": "/matrix-backdrop.jpg",
                        "vote_average": 8.2,
                    }
                ]
            }
        )


class TmdbSearchSession:
    def __init__(self):
        self.calls = []

    def get(self, url, *, params, headers, timeout):
        self.calls.append(url)
        if url.endswith("/49964/alternative_titles"):
            return JsonResponse({"titles": [{"title": "Khane-ye doost kojast?"}]})
        if url.endswith("/999/alternative_titles"):
            return JsonResponse({"titles": []})
        return JsonResponse(
            {
                "results": [
                    {
                        "id": 999,
                        "media_type": "movie",
                        "title": "Popular unrelated title",
                        "release_date": "2025-01-01",
                        "popularity": 900,
                    },
                    {
                        "id": 49964,
                        "media_type": "movie",
                        "title": "Where Is the Friend's House?",
                        "original_title": "خانه‌ی دوست کجاست؟",
                        "release_date": "1987-01-01",
                        "popularity": 1,
                    },
                ]
            }
        )


class TorznabResponse:
    ok = True
    status_code = 200

    def __init__(self, content):
        self.content = content.encode()


class CapabilitySession:
    def __init__(self):
        self.calls = []

    def get(self, url, *, params, headers, timeout):
        self.calls.append((url, params))
        if params.get("t") == "caps":
            return TorznabResponse(
                '<caps><searching><movie-search supportedParams="q,imdbid,tmdbid,year" />'
                "</searching></caps>"
            )
        if params.get("t") == "movie":
            return TorznabResponse(
                "<rss><channel><item><title>خانه‌ی دوست کجاست؟ 1987 1080p</title>"
                "<link>magnet:?xt=urn:btih:CCCC&amp;dn=friend</link>"
                '<torznab:attr xmlns:torznab="http://torznab.com/schemas/2015/feed" '
                'name="seeders" value="18" />'
                "</item></channel></rss>"
            )
        return FakeResponse()


def _notion_provider() -> NotionMovieProvider:
    provider = NotionMovieProvider(token="token", data_source_id="movie-source")
    provider._schema_cache["movie"] = {
        "Status": {"type": "status"},
        "Watched": {"type": "checkbox"},
    }
    return provider


def test_jackett_filters_low_seed_and_duplicate_results():
    session = FakeSession()
    provider = JackettReleaseProvider(
        base_url="http://127.0.0.1:9117",
        api_key="secret",
        min_seeders=5,
        session=session,
    )

    results = provider.search("Arrival 2016", "movie")

    assert session.params["Category"] == "2000"
    assert session.params["Query"] == "Arrival 2016"
    assert [item["title"] for item in results] == ["Arrival 2016 1080p"]
    assert results[0]["seeders"] == 18
    assert results[0]["quality_label"] == "1080p"
    assert "1080p" in results[0]["release_tags"]


def test_tmdb_multilingual_release_plan_uses_cached_native_and_transliterated_aliases():
    session = TmdbAliasSession()
    provider = TmdbCatalogProvider(api_key="key", session=session)

    _details, plan, context = provider.release_search_plan("movie", 49964)
    provider.release_search_plan("movie", 49964)

    assert [(item["kind"], item["query"]) for item in plan[:5]] == [
        ("imdb_id", "tt0093342"),
        ("tmdb_id", "49964"),
        ("native", "خانه‌ی دوست کجاست؟ 1987"),
        ("transliteration", "Khane-ye doost kojast? 1987"),
        ("international", "Where Is the Friend's House? 1987"),
    ]
    assert context["title_variants"][:3] == [
        "خانه‌ی دوست کجاست؟",
        "Khane-ye doost kojast?",
        "Khane-ye dust kojast?",
    ]
    assert sum(url.endswith("/alternative_titles") for url in session.calls) == 1


def test_tmdb_trending_returns_normalized_rankable_catalog_cards():
    session = TmdbTrendingSession()
    provider = TmdbCatalogProvider(api_key="key", session=session)

    items = provider.trending("movie", limit=12)

    assert items == [
        {
            "tmdb_id": 603,
            "media_type": "movie",
            "type_label": "Movie",
            "title": "The Matrix",
            "original_title": "The Matrix",
            "original_language": "",
            "overview": "",
            "year": 1999,
            "release_date": "1999-03-30",
            "poster_url": "https://image.tmdb.org/t/p/w500/matrix.jpg",
            "backdrop_url": "https://image.tmdb.org/t/p/w1280/matrix-backdrop.jpg",
            "rating": 8.2,
        }
    ]
    assert session.calls[0][0].endswith("/trending/movie/week")
    assert session.calls[0][1]["language"] == "en-US"

    catalog_items = provider.catalog("tv", "popular", limit=3)

    assert catalog_items[0]["media_type"] == "tv"
    assert catalog_items[0]["type_label"] == "Series"
    assert session.calls[1][0].endswith("/tv/popular")
    assert session.calls[1][1] == {"language": "en-US", "page": 1, "api_key": "key"}


def test_tmdb_discover_maps_shareable_browse_filters_to_tmdb_parameters():
    session = TmdbTrendingSession()
    provider = TmdbCatalogProvider(api_key="key", session=session)

    payload = provider.discover("tv", genre_id=18, year=2024, sort="rating", page=2)

    assert payload["page"] == 2
    assert payload["total_pages"] == 1
    assert payload["items"][0]["media_type"] == "tv"
    assert session.calls[0][0].endswith("/discover/tv")
    assert session.calls[0][1] == {
        "language": "en-US",
        "include_adult": "false",
        "sort_by": "vote_average.desc",
        "page": 2,
        "with_genres": 18,
        "first_air_date_year": 2024,
        "api_key": "key",
    }


def test_tmdb_search_ranks_cached_alternate_titles_above_popularity():
    session = TmdbSearchSession()
    provider = TmdbCatalogProvider(api_key="key", session=session)

    results = provider.search("Khane-ye doost kojast?", "movie")

    assert [item["tmdb_id"] for item in results] == [49964, 999]
    assert results[0]["alternate_titles"] == ["Khane-ye doost kojast?"]
    assert sum(url.endswith("/49964/alternative_titles") for url in session.calls) == 1


def test_jackett_search_plan_uses_advertised_ids_then_dedupes_alias_results():
    session = CapabilitySession()
    provider = JackettReleaseProvider(
        base_url="http://127.0.0.1:9117",
        api_key="secret",
        min_seeders=5,
        session=session,
    )
    attempts = [
        {"kind": "imdb_id", "label": "IMDb ID", "query": "tt0093342", "imdb_id": "tt0093342", "year": 1987},
        {"kind": "tmdb_id", "label": "TMDb ID", "query": "49964", "tmdb_id": "49964", "year": 1987},
        {"kind": "native", "label": "Original title", "query": "خانه‌ی دوست کجاست؟ 1987", "year": 1987},
    ]

    results, diagnostics = provider.search_plan(
        attempts,
        "movie",
        match_context={
            "tmdb_id": "49964",
            "imdb_id": "tt0093342",
            "year": 1987,
            "native_aliases": ["خانه‌ی دوست کجاست؟"],
            "title_variants": ["خانه‌ی دوست کجاست؟"],
        },
    )

    assert [item["title"] for item in results] == ["خانه‌ی دوست کجاست؟ 1987 1080p"]
    assert [item["kind"] for item in diagnostics] == ["imdb_id", "tmdb_id", "native"]
    assert [params.get("t") for _url, params in session.calls] == ["caps", "movie", "movie", None]


def test_jackett_never_surfaces_an_unrelated_high_seeder_release():
    provider = JackettReleaseProvider(
        base_url="http://127.0.0.1:9117",
        api_key="secret",
        min_seeders=5,
        session=FakeSession(),
    )

    results = provider._filter(
        [
            {
                "title": "An unrelated popular release 2024 1080p",
                "magnet_uri": "magnet:?xt=urn:btih:FFFF&dn=unrelated",
                "seeders": 900,
                "size": 1,
                "tracker": "TPB",
            }
        ],
        10,
        match_context={"title_variants": ["Where Is the Friend's House?"]},
    )

    assert results == []


def test_jackett_dedupes_the_same_release_returned_by_multiple_alias_queries():
    provider = JackettReleaseProvider(
        base_url="http://127.0.0.1:9117",
        api_key="secret",
        min_seeders=5,
        session=FakeSession(),
    )

    results = provider._filter(
        [
            {
                "title": "Khane-ye doost kojast? 1987 1080p",
                "magnet_uri": "magnet:?xt=urn:btih:AAAA&dn=first-query",
                "seeders": 12,
                "size": 1_500_000_000,
                "tracker": "Example",
            },
            {
                "title": "Khane-ye doost kojast? 1987 1080p",
                "magnet_uri": "magnet:?xt=urn:btih:BBBB&dn=second-query",
                "seeders": 18,
                "size": 1_500_000_000,
                "tracker": "Example",
            },
        ],
        10,
        match_context={"title_variants": ["Khane-ye doost kojast?"]},
    )

    assert [item["magnet_uri"] for item in results] == [
        "magnet:?xt=urn:btih:BBBB&dn=second-query"
    ]


def test_notion_movie_completion_uses_watched_for_legacy_finished_status():
    properties = _notion_provider()._media_properties(
        {"title": "Arrival", "tmdb_id": 329865, "media_type": "movie"},
        magnet_uri="",
        release_title="",
        season=None,
        episode=None,
        status="finished",
    )

    assert properties["Status"] == {"status": {"name": "Watched"}}
    assert _notion_status("Finished") == "watched"


def test_notion_mark_watched_does_not_write_finished_status():
    provider = _notion_provider()
    requests = []
    provider.ensure_writeback_schema = lambda *, kind: None
    provider._request = lambda method, path, **kwargs: requests.append((method, path, kwargs))

    provider.mark_watched("notion-page")

    assert requests[0][0:2] == ("PATCH", "/pages/notionpage")
    assert requests[0][2]["json"]["properties"]["Status"] == {
        "status": {"name": "Watched"}
    }


def test_notion_consolidates_finished_into_watched_and_removes_the_option():
    provider = _notion_provider()
    provider._schema_cache["movie"]["Status"]["status"] = {
        "options": [
            {"id": "finished", "name": "Finished", "color": "green"},
            {"id": "watched", "name": "Watched", "color": "green"},
        ]
    }
    provider._movie_pages_with_status = lambda _value, _property_type: [
        {
            "id": "finished-page",
            "properties": {"Status": {"type": "status", "status": {"name": "Finished"}}},
        }
    ]
    requests = []

    def request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        if method == "GET":
            return {"properties": provider._schema_cache["movie"]}
        return {}

    provider._request = request

    assert provider.consolidate_movie_completion_status() is True
    assert requests[1][0:2] == ("PATCH", "/pages/finishedpage")
    assert requests[1][2]["json"]["properties"]["Status"] == {
        "status": {"name": "Watched"}
    }
    options = requests[2][2]["json"]["properties"]["Status"]["status"]["options"]
    assert [option["name"] for option in options] == ["Watched"]


def test_jackett_returns_only_exact_episode_when_available():
    provider = JackettReleaseProvider(
        base_url="http://127.0.0.1:9117",
        api_key="secret",
        min_seeders=5,
        session=FakeSession(),
    )

    rows = [
        {
            "title": "The Sopranos S01E03 1080p",
            "magnet_uri": "magnet:?xt=urn:btih:1111&dn=sopranos-e03",
            "seeders": 18,
            "size": 1,
            "tracker": "TPB",
        },
        {
            "title": "The Sopranos Season 1 Complete 1080p",
            "magnet_uri": "magnet:?xt=urn:btih:2222&dn=sopranos-s1",
            "seeders": 10,
            "size": 1,
            "tracker": "TPB",
        },
        {
            "title": "The Sopranos S01E01 1080p",
            "magnet_uri": "magnet:?xt=urn:btih:3333&dn=sopranos-e01",
            "seeders": 7,
            "size": 1,
            "tracker": "TPB",
        },
    ]

    results = provider._filter(
        rows,
        10,
        match_context={
            "title_variants": ["The Sopranos"],
            "season": 1,
            "episode": 1,
            "episode_code": "S01E01",
            "alt_episode_code": "1x01",
        },
    )

    assert [item["title"] for item in results] == ["The Sopranos S01E01 1080p"]


def test_jackett_uses_season_pack_only_when_exact_episode_is_missing():
    provider = JackettReleaseProvider(
        base_url="http://127.0.0.1:9117",
        api_key="secret",
        min_seeders=5,
        session=FakeSession(),
    )

    rows = [
        {
            "title": "The Sopranos S01E03 1080p",
            "magnet_uri": "magnet:?xt=urn:btih:1111&dn=sopranos-e03",
            "seeders": 18,
            "size": 1,
            "tracker": "TPB",
        },
        {
            "title": "The Sopranos Season 1 Complete 1080p",
            "magnet_uri": "magnet:?xt=urn:btih:2222&dn=sopranos-s1",
            "seeders": 10,
            "size": 1,
            "tracker": "TPB",
        },
    ]

    results = provider._filter(
        rows,
        10,
        match_context={
            "title_variants": ["The Sopranos"],
            "season": 1,
            "episode": 1,
            "episode_code": "S01E01",
            "alt_episode_code": "1x01",
        },
    )

    assert [item["title"] for item in results] == [
        "The Sopranos Season 1 Complete 1080p"
    ]


def test_jackett_season_pack_mode_ignores_exact_and_side_mentions():
    provider = JackettReleaseProvider(
        base_url="http://127.0.0.1:9117",
        api_key="secret",
        min_seeders=5,
        session=FakeSession(),
    )

    rows = [
        {
            "title": "The Sopranos S01E01 1080p",
            "magnet_uri": "magnet:?xt=urn:btih:1111&dn=sopranos-e01",
            "seeders": 50,
            "size": 3_000_000_000,
            "tracker": "TPB",
        },
        {
            "title": "The Sopranos Season 1 Complete 1080p",
            "magnet_uri": "magnet:?xt=urn:btih:2222&dn=sopranos-s1",
            "seeders": 10,
            "size": 16_000_000_000,
            "tracker": "TPB",
        },
        {
            "title": "WISE GUY David Chase and The Sopranos S01 COMPLETE 1080p",
            "magnet_uri": "magnet:?xt=urn:btih:3333&dn=wise-guy",
            "seeders": 70,
            "size": 10_000_000_000,
            "tracker": "TPB",
        },
    ]

    results = provider._filter(
        rows,
        10,
        match_context={
            "title_variants": ["The Sopranos"],
            "season": 1,
        },
        mode="season_pack",
    )

    assert [item["title"] for item in results] == [
        "The Sopranos Season 1 Complete 1080p"
    ]


def test_jackett_release_profile_prefers_browser_and_subtitle_friendly_matches():
    provider = JackettReleaseProvider(
        base_url="http://127.0.0.1:9117",
        api_key="secret",
        min_seeders=5,
        session=FakeSession(),
    )

    rows = [
        {
            "title": "Arrival 2016 1080p BluRay x265",
            "magnet_uri": "magnet:?xt=urn:btih:1111&dn=arrival-hevc",
            "seeders": 20,
            "size": 2_000_000_000,
            "tracker": "TPB",
        },
        {
            "title": "Arrival 2016 1080p WEB-DL x264 Arabic Subs",
            "magnet_uri": "magnet:?xt=urn:btih:2222&dn=arrival-h264",
            "seeders": 20,
            "size": 2_200_000_000,
            "tracker": "TPB",
        },
    ]

    results = provider._filter(
        rows,
        10,
        match_context={"title_variants": ["Arrival"], "year": 2016},
    )

    assert [item["title"] for item in results] == [
        "Arrival 2016 1080p WEB-DL x264 Arabic Subs",
        "Arrival 2016 1080p BluRay x265",
    ]
    assert results[0]["codec_label"] == "H.264"
    assert results[0]["playback_label"] == "Browser friendly"
    assert results[0]["subtitle_label"] == "Subtitle signal"
    assert "Subs" in results[0]["release_tags"]
    assert results[1]["playback_label"] == "Transcode likely"
