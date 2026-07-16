from app.movies.integrations import JackettReleaseProvider


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
