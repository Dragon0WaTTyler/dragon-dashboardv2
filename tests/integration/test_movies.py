from app.extensions import db
from app.movies.models import Movie
from app.playback.models import PlaybackSource
from tests.conftest import csrf_from


class StubNotionProvider:
    configured = True

    def __init__(self):
        self.watched = []

    def list_items(self):
        return []

    def upsert_media(self, media, **kwargs):
        return {
            **media,
            "notion_page_id": "notion-page-1",
            "source": "Dragon",
            "status": kwargs.get("status") or "watching",
            "season": kwargs.get("season"),
            "episode": kwargs.get("episode"),
        }

    def mark_watched(self, page_id, *, started):
        self.watched.append((page_id, started))


class StubTmdbProvider:
    def search(self, query, media_type):
        assert query == "Arrival"
        assert media_type == "movie"
        return [
            {
                "tmdb_id": 329865,
                "media_type": "movie",
                "type_label": "Movie",
                "title": "Arrival",
                "year": 2016,
                "overview": "A linguist meets visitors.",
                "poster_url": "https://image.example/arrival.jpg",
            }
        ]

    def details(self, media_type, tmdb_id):
        if (media_type, tmdb_id) == ("tv", 1399):
            return {
                "tmdb_id": 1399,
                "media_type": "tv",
                "title": "The Sopranos",
                "original_title": "The Sopranos",
                "year": 1999,
                "overview": "Family and organized crime collide.",
                "poster_url": "https://image.example/sopranos.jpg",
                "runtime_minutes": 55,
                "genres": [{"name": "Crime"}],
                "directors": [],
                "cast": [],
                "external_ids": {"tmdb_id": "1399", "tmdb_type": "tv"},
                "seasons": [{"season_number": 1, "name": "Season 1", "episode_count": 13}],
            }
        assert (media_type, tmdb_id) == ("movie", 329865)
        return {
            "tmdb_id": 329865,
            "media_type": "movie",
            "title": "Arrival",
            "original_title": "Arrival",
            "year": 2016,
            "overview": "A linguist meets visitors.",
            "poster_url": "https://image.example/arrival.jpg",
            "runtime_minutes": 116,
            "genres": [{"name": "Science Fiction"}],
            "directors": [{"name": "Denis Villeneuve"}],
            "cast": [],
            "external_ids": {"tmdb_id": "329865", "tmdb_type": "movie"},
        }


def add_movie(app, **overrides) -> str:
    values = {
        "title": "Arrival",
        "normalized_title": "arrival",
        "year": 2016,
        "status": "watching",
        "personal_score": 4.5,
        "genres": [{"name": "Science Fiction"}],
    }
    values.update(overrides)
    with app.app_context():
        movie = Movie(**values)
        db.session.add(movie)
        db.session.commit()
        return movie.id


def test_movie_pages_are_protected_and_render_local_data(authenticated_client, app):
    movie_id = add_movie(app)
    assert app.test_client().get("/movies").status_code == 302

    listing = authenticated_client.get("/movies?q=arrival&genre=Science+Fiction")
    detail = authenticated_client.get(f"/movies/{movie_id}")
    assert listing.status_code == 200
    assert "Arrival" in listing.get_data(as_text=True)
    assert detail.status_code == 200
    assert "Science Fiction" in detail.get_data(as_text=True)


def test_movie_status_mutation_requires_csrf(authenticated_client, app):
    movie_id = add_movie(app)
    assert authenticated_client.post(
        f"/movies/{movie_id}/status", data={"status": "watched"}
    ).status_code == 400
    page = authenticated_client.get(f"/movies/{movie_id}")
    response = authenticated_client.post(
        f"/movies/{movie_id}/status",
        data={"status": "watched", "csrf_token": csrf_from(page)},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Movie, movie_id).status == "watched"


def test_movie_search_uses_tmdb_for_titles_missing_from_notion(authenticated_client, app):
    with app.app_context():
        app.config["DRAGON_NOTION_SYNC_ENABLED"] = True
        app.extensions["dragon_notion_movie_provider"] = StubNotionProvider()
        app.extensions["dragon_tmdb_catalog_provider"] = StubTmdbProvider()

    response = authenticated_client.get("/movies/api/search?q=Arrival&type=movie")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["library"] == []
    assert payload["discovery"][0]["title"] == "Arrival"
    assert payload["discovery"][0]["in_library"] is False


def test_import_writes_notion_and_creates_selected_player_source(authenticated_client, app):
    notion = StubNotionProvider()
    with app.app_context():
        app.config["DRAGON_NOTION_WRITEBACK_ENABLED"] = True
        app.extensions["dragon_notion_movie_provider"] = notion
        app.extensions["dragon_tmdb_catalog_provider"] = StubTmdbProvider()

    page = authenticated_client.get("/movies")
    response = authenticated_client.post(
        "/movies/api/import",
        headers={"X-CSRFToken": csrf_from(page)},
        json={
            "media_type": "movie",
            "tmdb_id": 329865,
            "magnet_uri": "magnet:?xt=urn:btih:AAAA&dn=arrival",
            "release_title": "Arrival 2016 1080p",
            "tracker": "YTS",
            "seeders": 18,
            "size": 1_500_000_000,
        },
    )

    assert response.status_code == 200
    movie_id = response.get_json()["movie_id"]
    with app.app_context():
        movie = db.session.get(Movie, movie_id)
        source = db.session.scalar(
            db.select(PlaybackSource).where(PlaybackSource.movie_id == movie_id)
        )
        assert movie.external_ids["notion_page_id"] == "notion-page-1"
        assert movie.external_ids["tmdb_id"] == "329865"
        assert source.selected is True
        assert source.locator.startswith("magnet:?")

    detail = authenticated_client.get(f"/movies/{movie_id}")
    token = csrf_from(detail)
    watch = authenticated_client.post(
        f"/movies/{movie_id}/watch", headers={"X-CSRFToken": token}
    )
    assert watch.status_code == 200
    assert notion.watched == [("notion-page-1", True)]


def test_library_add_defaults_series_to_season_one(authenticated_client, app):
    notion = StubNotionProvider()
    with app.app_context():
        app.config["DRAGON_NOTION_WRITEBACK_ENABLED"] = True
        app.extensions["dragon_notion_movie_provider"] = notion
        app.extensions["dragon_tmdb_catalog_provider"] = StubTmdbProvider()

    page = authenticated_client.get("/movies")
    response = authenticated_client.post(
        "/movies/api/library",
        headers={"X-CSRFToken": csrf_from(page)},
        json={"media_type": "tv", "tmdb_id": 1399, "season": 1},
    )

    assert response.status_code == 200
    movie_id = response.get_json()["movie_id"]
    with app.app_context():
        movie = db.session.get(Movie, movie_id)
        assert movie.title == "The Sopranos"
        assert movie.status == "want_to_watch"
        assert movie.media_type == "tv"
        assert movie.metadata_state["season"] == 1
