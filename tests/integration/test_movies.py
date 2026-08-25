from app.extensions import db
from app.movies import routes as movie_routes
from app.movies.models import Movie, MovieProgress
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
    assert "Arrival" in listing.get_data(as_text=True)
    assert detail.status_code == 200
    assert "Science Fiction" in detail.get_data(as_text=True)


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


def test_movies_hydrates_missing_recommendation_overview_from_tmdb(
    authenticated_client, app
):
    class OverviewTmdbProvider:
        configured = True

        def details(self, media_type, tmdb_id):
            assert (media_type, tmdb_id) == ("movie", 123)
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
    with app.app_context():
        app.extensions["dragon_tmdb_catalog_provider"] = OverviewTmdbProvider()

    page = authenticated_client.get("/movies")

    assert "A synopsis fetched from TMDB." in page.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Movie, movie_id).overview == "A synopsis fetched from TMDB."


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
