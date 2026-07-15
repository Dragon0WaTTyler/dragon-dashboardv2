from app.movies.providers import TmdbIdentityProvider


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/search/movie"):
            return FakeResponse({"results": []})
        if url.endswith("/search/tv"):
            return FakeResponse(
                {
                    "results": [
                        {
                            "id": 43017,
                            "name": "Great Teacher Onizuka",
                            "first_air_date": "1999-06-30",
                        }
                    ]
                }
            )
        if url.endswith("/tv/43017/external_ids"):
            return FakeResponse({"imdb_id": "tt0315008"})
        raise AssertionError(f"Unexpected request: {url}")


def test_tmdb_provider_falls_back_from_movie_to_tv_and_returns_imdb_id():
    session = FakeSession()
    provider = TmdbIdentityProvider(api_key="private-key", session=session)

    result = provider.resolve(
        title="Great Teacher Onizuka",
        year=1999,
        media_type="movie",
        external_ids={},
    )

    assert result == {
        "tmdb_id": "43017",
        "tmdb_type": "tv",
        "imdb_id": "tt0315008",
    }
    assert [call[0].rsplit("/", 2)[-2:] for call in session.calls] == [
        ["search", "movie"],
        ["search", "tv"],
        ["43017", "external_ids"],
    ]
    assert all(call[1]["timeout"] == 10 for call in session.calls)
    assert all(call[1]["params"]["api_key"] == "private-key" for call in session.calls)


def test_tmdb_provider_uses_existing_imdb_id_without_network():
    session = FakeSession()
    provider = TmdbIdentityProvider(session=session)

    result = provider.resolve(
        title="Arrival",
        year=2016,
        media_type="movie",
        external_ids={"imdb_id": "TT2543164"},
    )

    assert result == {"imdb_id": "tt2543164"}
    assert session.calls == []
