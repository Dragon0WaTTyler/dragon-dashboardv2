from app.extensions import db
from app.movies import routes as movie_routes
from app.movies.external_library import search_catalog
from app.movies.models import Movie, MovieProgress
from app.movies.services import MovieService, tv_season_workspace
from app.playback.models import PlaybackSource
from app.playback.services import PlaybackService
from tests.conftest import csrf_from


class StubNotionProvider:
    configured = True

    def __init__(self):
        self.watched = []
        self.scores = []

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

    def set_score(self, page_id, score_label):
        self.scores.append((page_id, score_label))


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

    def episodes(self, tmdb_id, season_number):
        assert (tmdb_id, season_number) == (1399, 1)
        return [
            {
                "season_number": 1,
                "episode_number": 1,
                "name": "Pilot",
                "overview": "",
                "still_url": "",
                "runtime_minutes": 60,
            }
        ]


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
    listing_html = listing.get_data(as_text=True)
    assert "Arrival" in listing_html
    assert 'data-ambient-level="subtle"' in listing_html
    assert "js/movies-ambient.js" in listing_html
    assert "js/movies-feedback.js" in listing_html
    assert detail.status_code == 200
    detail_html = detail.get_data(as_text=True)
    assert "Science Fiction" in detail_html
    assert 'data-ambient-level="subtle"' in detail_html
    assert "js/movies-ambient.js" in detail_html
    assert "js/movies-feedback.js" in detail_html


def test_movie_collections_are_authenticated_and_do_not_require_tmdb_for_the_index(
    authenticated_client, app
):
    assert app.test_client().get("/movies/collections").status_code == 302

    page = authenticated_client.get("/movies/collections")
    collection = authenticated_client.get("/movies/collections/psychological-thrillers")

    assert page.status_code == 200
    assert "Psychological thrillers" in page.get_data(as_text=True)
    assert collection.status_code == 200
    assert "fixed editorial query" in collection.get_data(as_text=True)


def test_legacy_notion_movie_gets_tmdb_identity_for_jackett_and_embed_sources(
    authenticated_client, app
):
    movie_id = add_movie(
        app,
        title="Yes Man",
        normalized_title="yes man",
        year=2008,
        external_ids={"notion_page_id": "legacy-notion-page"},
    )

    class LegacyTmdbProvider:
        configured = True

        def search(self, query, media_type):
            assert (query, media_type) == ("Yes Man", "movie")
            return [
                {
                    "tmdb_id": 1262,
                    "media_type": "movie",
                    "title": "Yes Man",
                    "original_title": "Yes Man",
                    "year": 2008,
                }
            ]

    with app.app_context():
        app.extensions["dragon_tmdb_catalog_provider"] = LegacyTmdbProvider()
        app.config.update(DRAGON_PLAYBACK_ENABLED=True, DRAGON_VIDSRC_ENABLED=True)

    detail = authenticated_client.get(f"/movies/{movie_id}")

    assert detail.status_code == 200
    html = detail.get_data(as_text=True)
    assert "Player 1 · VidSrc" in html
    assert "Search Jackett releases" in html
    assert 'js/movies.js' in html
    with app.app_context():
        movie = db.session.get(Movie, movie_id)
        assert movie.external_ids == {
            "notion_page_id": "legacy-notion-page",
            "tmdb_id": "1262",
            "tmdb_type": "movie",
        }


def test_jackett_lookup_only_runs_for_an_explicit_release_request(
    authenticated_client, app, monkeypatch
):
    movie_id = add_movie(
        app,
        title="Explicit Release Boundary",
        normalized_title="explicit release boundary",
        external_ids={"tmdb_id": "603", "tmdb_type": "movie"},
    )
    calls = []

    def fake_release_lookup(**values):
        calls.append(values)
        return {"media": {}, "queries": [], "queries_tried": [], "match_context": {}, "items": []}

    monkeypatch.setattr(movie_routes, "release_lookup", fake_release_lookup)

    assert authenticated_client.get("/movies").status_code == 200
    assert authenticated_client.get(f"/movies/{movie_id}").status_code == 200
    assert calls == []

    response = authenticated_client.get("/movies/api/releases?type=movie&tmdb_id=603")

    assert response.status_code == 200
    assert calls == [
        {"media_type": "movie", "tmdb_id": 603, "season": None, "episode": None, "mode": "auto"}
    ]


def test_movies_prioritizes_continue_watching_and_exposes_watch_next(authenticated_client, app):
    paused_id = add_movie(
        app,
        title="Paused film",
        normalized_title="paused film",
        runtime_minutes=100,
    )
    add_movie(
        app,
        title="Chosen next",
        normalized_title="chosen next",
        status="want_to_watch",
        personal_score=5,
        runtime_minutes=90,
    )
    finished_id = add_movie(
        app,
        title="Finished film",
        normalized_title="finished film",
        status="finished",
        runtime_minutes=100,
    )
    with app.app_context():
        db.session.add_all(
            [
                MovieProgress(
                    movie_id=paused_id,
                    current_seconds=3_000,
                    duration_seconds=6_000,
                    completed=False,
                ),
                MovieProgress(
                    movie_id=finished_id,
                    current_seconds=3_000,
                    duration_seconds=6_000,
                    completed=False,
                ),
            ]
        )
        db.session.commit()

    listing = authenticated_client.get("/movies")
    watch_next = authenticated_client.get("/movies/watch-next")

    assert listing.status_code == 200
    assert "Continue watching" in listing.get_data(as_text=True)
    assert "Paused film" in listing.get_data(as_text=True)
    assert "Finished film" not in listing.get_data(as_text=True)
    assert "Resume" in listing.get_data(as_text=True)
    assert watch_next.status_code == 200
    assert "Watch next" in watch_next.get_data(as_text=True)
    assert "Chosen next" in watch_next.get_data(as_text=True)


def test_movies_exposes_multiple_recommendations_for_try_another(authenticated_client, app):
    for title, year in (("First pick", 1994), ("Second pick", 1997)):
        add_movie(
            app,
            title=title,
            normalized_title=title.casefold(),
            year=year,
            status="want_to_watch",
            category="movie",
            source="My library",
            overview=f"Overview for {title}.",
            directors=[{"name": "A director"}],
            genres=[{"name": "Drama"}],
        )

    page = authenticated_client.get("/movies")
    html = page.get_data(as_text=True)

    assert page.status_code == 200
    assert "What should I watch?" in html
    assert "Try another" in html
    assert 'data-recommendation-items="' in html
    assert "First pick" in html
    assert "Second pick" in html


def test_movies_home_does_not_hydrate_missing_recommendation_overview_from_tmdb(
    authenticated_client, app
):
    class OverviewTmdbProvider:
        configured = True

        def __init__(self):
            self.detail_calls = []

        def details(self, media_type, tmdb_id):
            self.detail_calls.append((media_type, tmdb_id))
            return {"overview": "A synopsis fetched from TMDB."}

    movie_id = add_movie(
        app,
        title="Missing overview",
        normalized_title="missing overview",
        status="want_to_watch",
        category="movie",
        source="My library",
        overview="",
        external_ids={"tmdb_id": "123", "tmdb_type": "movie"},
        directors=[{"name": "A director"}],
        genres=[{"name": "Drama"}],
    )
    provider = OverviewTmdbProvider()
    with app.app_context():
        app.extensions["dragon_tmdb_catalog_provider"] = provider

    page = authenticated_client.get("/movies")

    assert "A synopsis fetched from TMDB." not in page.get_data(as_text=True)
    assert provider.detail_calls == []
    with app.app_context():
        assert db.session.get(Movie, movie_id).overview == ""


def test_movie_status_mutation_requires_csrf(authenticated_client, app):
    movie_id = add_movie(app)
    assert (
        authenticated_client.post(
            f"/movies/{movie_id}/status", data={"status": "watched"}
        ).status_code
        == 400
    )
    page = authenticated_client.get(f"/movies/{movie_id}")
    response = authenticated_client.post(
        f"/movies/{movie_id}/status",
        data={"status": "watched", "csrf_token": csrf_from(page)},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Movie, movie_id).status == "watched"


def test_movie_score_uses_notion_labels_and_writes_back(authenticated_client, app):
    notion = StubNotionProvider()
    with app.app_context():
        app.config["DRAGON_NOTION_WRITEBACK_ENABLED"] = True
        app.extensions["dragon_notion_movie_provider"] = notion
        movie = Movie(
            title="Arrival",
            normalized_title="arrival",
            status="watching",
            external_ids={"notion_page_id": "notion-page-1"},
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    page = authenticated_client.get(f"/movies/{movie_id}")
    response = authenticated_client.post(
        f"/movies/{movie_id}/score",
        data={"score": "masterpiece", "csrf_token": csrf_from(page)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Personal score and Notion were updated." in html
    assert "masterpiece" in html
    with app.app_context():
        movie = db.session.get(Movie, movie_id)
        assert movie.personal_score == 4.0
        assert movie.metadata_state["personal_score_label"] == "masterpiece"
    assert notion.scores == [("notion-page-1", "masterpiece")]


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
    watch = authenticated_client.post(f"/movies/{movie_id}/watch", headers={"X-CSRFToken": token})
    assert watch.status_code == 200
    assert notion.watched == [("notion-page-1", True)]


def test_movie_api_import_unexpected_errors_stay_json(authenticated_client, app, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(movie_routes, "import_release", boom)

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

    assert response.status_code == 500
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "internal_error"
    assert payload["error"]["message"] == "The request could not be completed."


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


def test_resolve_tv_episode_source_updates_episode_page_with_fallback(
    authenticated_client, app, monkeypatch
):
    notion = StubNotionProvider()
    with app.app_context():
        app.config["DRAGON_NOTION_WRITEBACK_ENABLED"] = True
        app.config["DRAGON_PLAYBACK_ENABLED"] = True
        app.config["DRAGON_MAGNETS_ENABLED"] = True
        app.config["DRAGON_MULTIEMBED_ENABLED"] = False
        app.config["DRAGON_MULTIEMBED_VIP_ENABLED"] = False
        app.extensions["dragon_notion_movie_provider"] = notion
        app.extensions["dragon_tmdb_catalog_provider"] = StubTmdbProvider()

        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            external_ids={"tmdb_id": "1399", "tmdb_type": "tv"},
            metadata_state={
                "season": 1,
                "episode": 1,
                "tv_total_seasons": 1,
                "tv_total_episodes": 2,
                "tv_seasons": [
                    {"season_number": 1, "name": "Season 1", "episode_count": 2, "poster_url": ""}
                ],
                "tv_episodes": {
                    "1": [
                        {
                            "season_number": 1,
                            "episode_number": 1,
                            "name": "Pilot",
                            "overview": "",
                            "still_url": "",
                            "runtime_minutes": 60,
                        },
                        {
                            "season_number": 1,
                            "episode_number": 2,
                            "name": "46 Long",
                            "overview": "",
                            "still_url": "",
                            "runtime_minutes": 60,
                        },
                    ]
                },
            },
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    def fake_release_lookup(*, mode, **kwargs):
        if mode == "exact_episode":
            return {"items": []}
        return {
            "items": [
                {
                    "magnet_uri": "magnet:?xt=urn:btih:AAAA&dn=sopranos-s01-pack",
                    "title": "The Sopranos S01 1080p pack",
                    "tracker": "YTS",
                    "seeders": 42,
                    "size": 5_000_000_000,
                }
            ]
        }

    monkeypatch.setattr(movie_routes, "release_lookup", fake_release_lookup)

    page = authenticated_client.get(f"/movies/{movie_id}/seasons/1/episodes/1")
    response = authenticated_client.post(
        f"/movies/{movie_id}/seasons/1/episodes/1/resolve-source",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Saved the best season-pack fallback for this episode." in html
    assert "A season-pack fallback is already saved for this page." in html
    assert "Local source ready" in html
    assert 'data-kind="local"' in html

    with app.app_context():
        sources = list(
            db.session.scalars(db.select(PlaybackSource).where(PlaybackSource.movie_id == movie_id))
        )
        assert any(
            source.season == 1
            and source.episode is None
            and source.source_role == "season_pack_fallback"
            for source in sources
        )

    next_episode = authenticated_client.get(f"/movies/{movie_id}/seasons/1/episodes/2")
    next_html = next_episode.get_data(as_text=True)
    assert "A season-pack fallback is already saved for this page." in next_html
    assert 'data-source-season-pack="true"' in next_html
    assert "data-player-pack-browser" in next_html


def test_direct_embed_keeps_manual_jackett_search_available(authenticated_client, app, monkeypatch):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            external_ids={"tmdb_id": "1399", "tmdb_type": "tv"},
            metadata_state={
                "tv_seasons": [{"season_number": 1, "episode_count": 1}],
                "tv_episodes": {"1": [{"season_number": 1, "episode_number": 1, "name": "Pilot"}]},
            },
        )
        db.session.add(movie)
        db.session.commit()
        PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="videotube",
            provider_asset_id="iuki4kda2u7l",
            label="VideoTube · Arabic",
            season=1,
            episode=1,
        )
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_VIDEOTUBE_ENABLED=True,
        DRAGON_VIDEOTUBE_EMBED_URL="https://down.vidtube.one/embed-{asset_id}.html",
    )

    def should_not_search(**_kwargs):
        raise AssertionError("Jackett must not run when a direct embed is available")

    monkeypatch.setattr(movie_routes, "release_lookup", should_not_search)
    page = authenticated_client.get(f"/movies/{movie_id}/seasons/1/episodes/1")
    response = authenticated_client.post(
        f"/movies/{movie_id}/seasons/1/episodes/1/resolve-source",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "direct playback source is already available" in html
    assert "Find Best Source" not in html
    assert "data-inline-release-browser" in html
    assert "Search Jackett for Season 1" in html


def test_release_api_exposes_safe_query_diagnostics(authenticated_client, monkeypatch):
    monkeypatch.setattr(
        movie_routes,
        "release_lookup",
        lambda **_kwargs: {
            "media": {"tmdb_id": 49964},
            "queries": ["خانه‌ی دوست کجاست؟ 1987"],
            "queries_tried": [
                {
                    "kind": "native",
                    "label": "Original title",
                    "query": "خانه‌ی دوست کجاست؟ 1987",
                    "status": "completed",
                    "result_count": 1,
                }
            ],
            "match_context": {"tmdb_id": "49964"},
            "items": [],
        },
    )

    response = authenticated_client.get("/movies/api/releases?type=movie&tmdb_id=49964")

    assert response.status_code == 200
    assert response.get_json()["queries_tried"] == [
        {
            "kind": "native",
            "label": "Original title",
            "query": "خانه‌ی دوست کجاست؟ 1987",
            "status": "completed",
            "result_count": 1,
        }
    ]


def test_tv_season_exposes_jackett_season_pack_chooser(authenticated_client, app):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            external_ids={"tmdb_id": "1399", "tmdb_type": "tv"},
            metadata_state={
                "tv_total_seasons": 1,
                "tv_total_episodes": 1,
                "tv_seasons": [
                    {"season_number": 1, "name": "Season 1", "episode_count": 1, "poster_url": ""}
                ],
                "tv_episodes": {
                    "1": [
                        {
                            "season_number": 1,
                            "episode_number": 1,
                            "name": "Pilot",
                            "overview": "",
                            "still_url": "",
                            "runtime_minutes": 60,
                        }
                    ]
                },
            },
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    response = authenticated_client.get(f"/movies/{movie_id}/seasons/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "data-inline-release-browser" in html
    assert 'data-fixed-season="1"' in html
    assert "data-season-pack-load" in html


def test_tv_episode_hides_local_player_when_playback_flags_are_disabled(authenticated_client, app):
    with app.app_context():
        movie = Movie(
            title="Disabled Playback",
            normalized_title="disabled playback",
            media_type="tv",
            external_ids={"tmdb_id": "1399", "tmdb_type": "tv"},
            metadata_state={
                "tv_total_seasons": 1,
                "tv_total_episodes": 1,
                "tv_seasons": [
                    {"season_number": 1, "name": "Season 1", "episode_count": 1, "poster_url": ""}
                ],
                "tv_episodes": {
                    "1": [
                        {
                            "season_number": 1,
                            "episode_number": 1,
                            "name": "Pilot",
                            "overview": "",
                            "still_url": "",
                            "runtime_minutes": 60,
                        }
                    ]
                },
            },
        )
        db.session.add(movie)
        db.session.flush()
        db.session.add(
            PlaybackSource(
                movie_id=movie.id,
                kind="magnet",
                label="S01 season pack Jackett magnet",
                locator="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
                season=1,
                episode=1,
                source_role="season_pack_fallback",
                metadata_json={
                    "season_pack": True,
                    "season": 1,
                    "episode": 1,
                    "release_mode": "season_pack",
                },
                selected=True,
            )
        )
        db.session.commit()
        movie_id = movie.id

    app.config["DRAGON_PLAYBACK_ENABLED"] = False
    app.config["DRAGON_MAGNETS_ENABLED"] = False
    app.config["DRAGON_VIDSRC_ENABLED"] = False

    response = authenticated_client.get(f"/movies/{movie_id}/seasons/1/episodes/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="episode-player"' not in html
    assert "Play selected episode from pack" not in html
    assert 'data-local-endpoint=""' not in html


def test_what_should_i_watch_api_uses_only_personal_unwatched_entries(authenticated_client, app):
    with app.app_context():
        available = Movie(title="Available", normalized_title="available")
        watched = Movie(title="Watched", normalized_title="watched")
        db.session.add_all([available, watched])
        db.session.commit()
        MovieService.set_status(available, "want_to_watch")
        MovieService.set_status(watched, "watched")
        available_id = available.id

    response = authenticated_client.get("/movies/api/what-should-i-watch")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["item"]["id"] == available_id
    assert payload["item"]["eligibility_reason"] == "From your personal unwatched library."


def test_movies_home_prioritizes_personal_focus_and_want_to_watch(authenticated_client, app):
    with app.app_context():
        available = Movie(title="Personal choice", normalized_title="personal choice")
        watched = Movie(title="Already watched", normalized_title="already watched")
        db.session.add_all([available, watched])
        db.session.commit()
        MovieService.set_status(available, "want_to_watch")
        MovieService.set_status(watched, "watched")

        page = authenticated_client.get("/movies")
    html = page.get_data(as_text=True)

    assert page.status_code == 200
    assert 'data-home-focus' in html
    assert "From your personal library" in html
    assert "Personal choice" in html
    assert "Want to watch" in html
    assert 'data-home-focus-shuffle' in html


def test_movies_home_renders_cached_tmdb_discovery_rails(authenticated_client, app):
    class RailProvider:
        configured = True

        def __init__(self):
            self.calls = []
            self.catalog_calls = []

        def trending(self, media_type, *, limit):
            self.calls.append((media_type, limit))
            return [
                {
                    "tmdb_id": 81 if media_type == "movie" else 82,
                    "media_type": media_type,
                    "title": f"Trending {media_type}",
                    "poster_url": "",
                    "year": 2026,
                    "rating": 7.5,
                }
            ]

        def catalog(self, media_type, kind, *, limit):
            self.catalog_calls.append((media_type, kind, limit))
            return [
                {
                    "tmdb_id": len(self.catalog_calls) + 300,
                    "media_type": media_type,
                    "title": f"{kind} {media_type}",
                    "poster_url": "",
                    "year": 2026,
                    "rating": 7.5,
                }
            ]

    provider = RailProvider()
    with app.app_context():
        app.extensions["dragon_tmdb_catalog_provider"] = provider

    first = authenticated_client.get("/movies")
    second = authenticated_client.get("/movies")
    html = first.get_data(as_text=True)

    assert first.status_code == 200
    assert second.status_code == 200
    assert 'data-discovery-rail="trending_movies"' in html
    assert "Trending Movies" in html
    assert 'href="/movies/discover/movie/81"' in html
    assert 'data-discovery-rail="popular_series"' in html
    assert "Top 10 Movies" in html
    assert provider.calls == [("movie", 12), ("tv", 12)]
    assert provider.catalog_calls == [
        ("movie", "popular", 12),
        ("tv", "popular", 12),
        ("movie", "top_rated", 12),
        ("tv", "top_rated", 12),
        ("movie", "upcoming", 12),
        ("movie", "now_playing", 12),
    ]


def test_movies_browse_route_restores_movie_filter_url_state(authenticated_client, app):
    class BrowseProvider:
        configured = True

        def genres(self, media_type):
            return [{"id": 18, "name": "Drama"}]

        def discover(self, media_type, **kwargs):
            assert media_type == "movie"
            assert kwargs == {"genre_id": 18, "year": 1999, "sort": "rating", "page": 2}
            return {
                "items": [
                    {
                        "tmdb_id": 603,
                        "media_type": "movie",
                        "title": "The Matrix",
                        "poster_url": "",
                        "year": 1999,
                        "rating": 8.2,
                    }
                ],
                "page": 2,
                "total_pages": 3,
            }

    with app.app_context():
        app.extensions["dragon_tmdb_catalog_provider"] = BrowseProvider()

    response = authenticated_client.get("/movies/browse/movie?genre=18&year=1999&sort=rating&page=2")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Browse movies" in html
    assert 'value="18" selected' in html
    assert 'value="rating" selected' in html
    assert 'href="/movies/discover/movie/603"' in html
    assert "Page 2 of 3" in html

    shows = authenticated_client.get("/movies/shows?sort=title", follow_redirects=False)

    assert shows.status_code == 302
    assert shows.headers["Location"].endswith("/movies/browse/tv?sort=title")


def test_multilingual_search_matches_original_and_transliterated_local_titles(app):
    class MultilingualProvider:
        def __init__(self):
            self.search_calls = []
            self.id_calls = []

        def search(self, query, media_type):
            self.search_calls.append((query, media_type))
            return [
                {
                    "tmdb_id": 49964,
                    "media_type": "movie",
                    "title": "Where Is the Friend's House?",
                    "original_title": "خانه‌ی دوست کجاست؟",
                    "alternate_titles": ["Khane-ye doost kojast?"],
                    "year": 1987,
                    "poster_url": "",
                    "overview": "",
                }
            ]

        def lookup_tmdb_id(self, tmdb_id, media_type):
            self.id_calls.append((tmdb_id, media_type))
            return self.search("tmdb result", media_type)

    provider = MultilingualProvider()
    with app.app_context():
        movie = Movie(
            title="Where Is the Friend's House?",
            normalized_title="where is the friend s house",
            original_title="خانه‌ی دوست کجاست؟",
            year=1987,
            external_ids={"tmdb_id": "49964", "tmdb_type": "movie"},
            metadata_state={"transliterations": ["Khane-ye doost kojast?"]},
        )
        db.session.add(movie)
        db.session.commit()
        app.extensions["dragon_tmdb_catalog_provider"] = provider

        transliterated = search_catalog("Khane-ye doost kojast? 1987", "all")
        native = search_catalog("خانه‌ی دوست کجاست؟", "movie")
        by_id = search_catalog("tmdb:49964", "movie")

    assert [item["local_id"] for item in transliterated["library"]] == [movie.id]
    assert transliterated["discovery"] == []
    assert [item["local_id"] for item in native["library"]] == [movie.id]
    assert [item["local_id"] for item in by_id["library"]] == [movie.id]
    assert by_id["discovery"] == []
    assert provider.id_calls == [(49964, "movie")]


def test_explicit_detail_refresh_caches_tmdb_sections_without_touching_playback(
    authenticated_client, app
):
    class DetailProvider:
        def details(self, media_type, tmdb_id):
            assert (media_type, tmdb_id) == ("movie", 603)
            return {
                "overview": "A cached synopsis.",
                "poster_url": "https://image.test/poster.jpg",
                "genres": [{"name": "Science Fiction"}],
                "directors": [{"name": "Lana Wachowski"}],
                "cast": [{"name": "Keanu Reeves", "character": "Neo", "profile_url": ""}],
                "runtime_minutes": 136,
                "tmdb_detail": {
                    "backdrop_url": "https://image.test/backdrop.jpg",
                    "tagline": "Welcome to the real world.",
                    "original_language": "en",
                    "countries": ["United States"],
                    "certification": "R",
                    "tmdb_rating": 8.2,
                    "trailers": [
                        {
                            "name": "Official Trailer",
                            "url": "https://youtube.test/x",
                            "official": True,
                        }
                    ],
                    "reviews": [{"author": "TMDB member", "content": "Real review", "url": ""}],
                    "similar": [],
                    "recommendations": [],
                },
            }

    with app.app_context():
        movie = Movie(
            title="The Matrix",
            normalized_title="the matrix",
            external_ids={"tmdb_id": "603", "tmdb_type": "movie"},
        )
        db.session.add(movie)
        db.session.commit()
        db.session.add(
            MovieProgress(
                movie_id=movie.id,
                current_seconds=720,
                duration_seconds=7_200,
                completed=False,
            )
        )
        db.session.commit()
        movie_id = movie.id
        app.extensions["dragon_tmdb_catalog_provider"] = DetailProvider()

    page = authenticated_client.get(f"/movies/{movie_id}")
    response = authenticated_client.post(
        f"/movies/{movie_id}/refresh-metadata",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "TMDB detail metadata refreshed locally." in response.get_data(as_text=True)
    with app.app_context():
        refreshed = db.session.get(Movie, movie_id)
        assert refreshed.runtime_minutes == 136
        assert refreshed.metadata_state["tmdb_detail"]["tmdb_rating"] == 8.2
        progress = MovieProgress.query.filter_by(movie_id=movie_id, scope_key="movie").one()
        assert (progress.current_seconds, progress.duration_seconds, progress.completed) == (
            720,
            7_200,
            False,
        )


def test_favorite_is_independent_from_lifecycle_and_progress(authenticated_client, app):
    movie_id = add_movie(app, title="Favorite title", normalized_title="favorite title")
    with app.app_context():
        db.session.add(
            MovieProgress(
                movie_id=movie_id,
                current_seconds=600,
                duration_seconds=6_000,
            )
        )
        db.session.commit()

    detail = authenticated_client.get(f"/movies/{movie_id}")
    response = authenticated_client.post(
        f"/movies/{movie_id}/favorite",
        data={"favorite": "1", "csrf_token": csrf_from(detail)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Remove favorite" in response.get_data(as_text=True)
    favorites = authenticated_client.get("/movies?favorite=1")
    assert "Favorite title" in favorites.get_data(as_text=True)
    with app.app_context():
        movie = db.session.get(Movie, movie_id)
        assert movie.library_entry.is_favorite is True
        progress = MovieProgress.query.filter_by(movie_id=movie_id, scope_key="movie").one()
        assert (progress.current_seconds, progress.duration_seconds) == (600, 6_000)


def test_custom_lists_are_owner_scoped_and_keep_movie_state(authenticated_client, app):
    movie_id = add_movie(app, title="List title", normalized_title="list title")
    page = authenticated_client.get("/movies/lists")
    created = authenticated_client.post(
        "/movies/lists",
        data={"title": "Weekend", "description": "For Saturday", "csrf_token": csrf_from(page)},
        follow_redirects=True,
    )
    assert created.status_code == 200
    assert "Weekend" in created.get_data(as_text=True)
    with app.app_context():
        from app.movies.models import MovieCustomList

        custom_list_id = MovieCustomList.query.one().id
    detail = authenticated_client.get(f"/movies/{movie_id}")
    added = authenticated_client.post(
        f"/movies/items/{movie_id}/lists",
        data={"custom_list_id": custom_list_id, "csrf_token": csrf_from(detail)},
        follow_redirects=True,
    )
    assert added.status_code == 200
    listing = authenticated_client.get("/movies/lists")
    assert "List title" in listing.get_data(as_text=True)


def test_tv_detail_refresh_caches_real_seasons_and_preserves_specials(
    authenticated_client, app
):
    class TvDetailProvider:
        def details(self, media_type, tmdb_id):
            assert (media_type, tmdb_id) == ("tv", 1399)
            return {
                "tmdb_id": 1399,
                "media_type": "tv",
                "title": "Example Series",
                "overview": "A real cached series overview.",
                "poster_url": "https://image.test/series.jpg",
                "genres": [{"name": "Drama"}],
                "directors": [],
                "cast": [],
                "runtime_minutes": 55,
                "seasons": [
                    {
                        "tmdb_id": 10,
                        "name": "Specials",
                        "season_number": 0,
                        "episode_count": 1,
                        "air_date": "1998-12-31",
                        "poster_url": "",
                    },
                    {
                        "tmdb_id": 11,
                        "name": "Season 1",
                        "season_number": 1,
                        "episode_count": 1,
                        "air_date": "1999-01-10",
                        "poster_url": "",
                    },
                ],
                "tmdb_detail": {
                    "backdrop_url": "",
                    "tagline": "A real show.",
                    "original_language": "en",
                    "countries": ["United States"],
                    "certification": "",
                    "tmdb_rating": 8.0,
                    "trailers": [],
                    "reviews": [],
                    "similar": [],
                    "recommendations": [],
                },
            }

        def episodes(self, tmdb_id, season_number):
            assert tmdb_id == 1399
            return [
                {
                    "tmdb_id": 100 + season_number,
                    "season_number": season_number,
                    "episode_number": 1,
                    "name": "Prelude" if season_number == 0 else "Pilot",
                    "overview": "Episode overview.",
                    "still_url": "https://image.test/still.jpg",
                    "runtime_minutes": 55,
                    "air_date": "1999-01-01",
                }
            ]

    with app.app_context():
        movie = Movie(
            title="Example Series",
            normalized_title="example series",
            media_type="tv",
            external_ids={"tmdb_id": "1399", "tmdb_type": "tv"},
        )
        db.session.add(movie)
        db.session.commit()
        db.session.add(
            MovieProgress(
                movie_id=movie.id,
                season=0,
                episode=1,
                current_seconds=900,
                duration_seconds=3_300,
            )
        )
        db.session.commit()
        movie_id = movie.id
        app.extensions["dragon_tmdb_catalog_provider"] = TvDetailProvider()

    page = authenticated_client.get(f"/movies/{movie_id}")
    response = authenticated_client.post(
        f"/movies/{movie_id}/refresh-metadata",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Specials" in html
    assert "Season 1" in html
    assert "Prelude" not in html
    with app.app_context():
        workspace = tv_season_workspace(db.session.get(Movie, movie_id), season_number=0)
        assert [episode["name"] for episode in workspace["episodes"]] == ["Prelude"], workspace[
            "catalog"
        ]
        assert workspace["episodes"][0]["progress"]["percent"] == 27
        assert workspace["resume_target"] is None
    specials = authenticated_client.get(f"/movies/{movie_id}/seasons/0")
    assert specials.status_code == 200
    specials_html = specials.get_data(as_text=True)
    assert "Episode browser" in specials_html
    assert "Prelude" in specials_html
    with app.app_context():
        refreshed = db.session.get(Movie, movie_id)
        assert refreshed.metadata_state["tv_total_seasons"] == 1
        assert refreshed.metadata_state["tv_episodes"]["0"][0]["name"] == "Prelude"
