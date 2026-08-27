from app.movies.rails import DISCOVERY_RAILS, discovery_rails, provider_context


class StubTrendingProvider:
    configured = True

    def __init__(self):
        self.calls: list[tuple[str, int]] = []
        self.catalog_calls: list[tuple[str, str, int]] = []

    def trending(self, media_type: str, *, limit: int):
        self.calls.append((media_type, limit))
        return [
            {
                "tmdb_id": 100 if media_type == "movie" else 200,
                "media_type": media_type,
                "title": f"Trending {media_type}",
                "poster_url": "https://example.test/poster.jpg",
                "year": 2026,
                "rating": 8.3,
            },
            {
                "tmdb_id": 100 if media_type == "movie" else 200,
                "media_type": media_type,
                "title": "Duplicate",
            },
        ]

    def catalog(self, media_type: str, kind: str, *, limit: int):
        self.catalog_calls.append((media_type, kind, limit))
        return [
            {
                "tmdb_id": len(self.catalog_calls) + 300,
                "media_type": media_type,
                "title": f"{kind} {media_type}",
                "poster_url": "",
                "year": 2026,
                "rating": 7.2,
            }
        ]


def test_discovery_rails_are_cached_and_keep_remote_cards_out_of_personal_state(app):
    provider = StubTrendingProvider()
    with app.app_context():
        app.extensions["dragon_tmdb_catalog_provider"] = provider

        first = discovery_rails()
        second = discovery_rails()

    assert provider.calls == [("movie", 12), ("tv", 12)]
    assert provider.catalog_calls == [
        ("movie", "popular", 12),
        ("tv", "popular", 12),
        ("movie", "top_rated", 12),
        ("tv", "top_rated", 12),
        ("movie", "upcoming", 12),
        ("movie", "now_playing", 12),
    ]
    assert [rail["id"] for rail in first] == [item.id for item in DISCOVERY_RAILS]
    assert second == first
    assert first[0]["items"] == [
        {
            "tmdb_id": 100,
            "media_type": "movie",
            "title": "Trending movie",
            "poster_url": "https://example.test/poster.jpg",
            "year": 2026,
            "rating": 8.3,
            "rank": 1,
            "detail_url": "/movies/discover/movie/100",
        }
    ]


def test_provider_context_shares_selection_for_movie_and_tv_availability(app):
    class Provider(StubTrendingProvider):
        def provider_catalog(self, media_type, *, region):
            return [
                {"id": 8, "name": "Netflix", "logo_url": "logo"},
                {"id": 9, "name": "Prime Video", "logo_url": ""},
            ]

        def discover(self, media_type, **kwargs):
            assert kwargs == {
                "provider_id": 8,
                "region": "US",
                "sort": "popular",
                "page": 1,
            }
            return {
                "items": [
                    {
                        "tmdb_id": 100 if media_type == "movie" else 200,
                        "media_type": media_type,
                        "title": media_type,
                    }
                ],
                "page": 1,
                "total_pages": 1,
            }

    with app.app_context():
        app.extensions["dragon_tmdb_catalog_provider"] = Provider()
        result = provider_context(region="US", selected_provider_id=8)

    assert result["selected_provider"]["name"] == "Netflix"
    assert [rail["content_type"] for rail in result["rails"]] == ["movie", "tv"]
    assert all(rail["provider_id"] == 8 for rail in result["rails"])
