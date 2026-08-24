from app.movies.integrations import JackettReleaseProvider, NotionMovieProvider, _notion_status


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
