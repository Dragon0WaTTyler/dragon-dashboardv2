from app.movies.browse import browse_catalog, parse_browse_query


class StubBrowseProvider:
    configured = True

    def __init__(self):
        self.discover_calls = []
        self.genre_calls = []

    def genres(self, media_type):
        self.genre_calls.append(media_type)
        return [{"id": 18, "name": "Drama"}]

    def discover(self, media_type, **kwargs):
        self.discover_calls.append((media_type, kwargs))
        return {
            "items": [
                {
                    "tmdb_id": 603,
                    "media_type": media_type,
                    "title": "The Matrix",
                    "poster_url": "",
                    "year": 1999,
                    "rating": 8.2,
                }
            ],
            "page": kwargs["page"],
            "total_pages": 3,
        }


def test_browse_query_is_shareable_and_validates_url_filters():
    query, errors = parse_browse_query(
        "movie", {"genre": "18", "year": "1999", "sort": "rating", "page": "2"}
    )

    assert errors == {}
    assert (query.media_type, query.genre_id, query.year, query.sort, query.page) == (
        "movie",
        18,
        1999,
        "rating",
        2,
    )

    query, errors = parse_browse_query("tv", {"genre": "wrong", "sort": "nope"})

    assert query.genre_id is None
    assert query.sort == "popular"
    assert set(errors) == {"genre", "sort"}


def test_browse_catalog_caches_catalog_and_genres_without_personal_state(app):
    provider = StubBrowseProvider()
    query, _ = parse_browse_query("movie", {"genre": "18", "year": "1999"})
    with app.app_context():
        app.extensions["dragon_tmdb_catalog_provider"] = provider
        first = browse_catalog(query)
        second = browse_catalog(query)

    assert provider.genre_calls == ["movie"]
    assert provider.discover_calls == [
        ("movie", {"genre_id": 18, "year": 1999, "sort": "popular", "page": 1})
    ]
    assert second == first
    assert first["items"][0]["detail_url"] == "/movies/discover/movie/603"
