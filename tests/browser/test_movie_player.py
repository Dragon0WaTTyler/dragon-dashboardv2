import time

import pytest

from app.extensions import db
from app.movies.models import Movie
from app.playback.models import PlaybackSource

pytestmark = pytest.mark.browser


def sign_in(page, base_url: str):
    page.goto(f"{base_url}/auth/login")
    page.get_by_label("Username").fill("walid")
    page.get_by_label("Password").fill("correct horse battery staple")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"{base_url}/")


def test_movie_player_switches_between_vidsrc_and_local_without_overflow(page, live_app, app):
    with app.app_context():
        movie = Movie(
            title="Source Switch",
            normalized_title="source switch",
            external_ids={"imdb_id": "tt2543164"},
        )
        db.session.add(movie)
        db.session.flush()
        db.session.add(
            PlaybackSource(
                movie_id=movie.id,
                kind="magnet",
                label="FHD magnet",
                locator=("magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"),
            )
        )
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MAGNETS_ENABLED=True,
        DRAGON_VIDSRC_ENABLED=True,
        DRAGON_SUBTITLES_ENABLED=True,
        DRAGON_SUBDL_API_KEY="private-key",
    )
    page.route(
        "**/playback/movie/*/subtitles",
        lambda route: route.fulfill(
            json={
                "ok": True,
                "items": [
                    {
                        "language": "ar",
                        "language_name": "Arabic",
                        "label": "Arabic release",
                        "hearing_impaired": False,
                        "track_url": "/playback/movie/test/subtitles/track/arabic",
                    },
                    {
                        "language": "en",
                        "language_name": "English",
                        "label": "English release",
                        "hearing_impaired": False,
                        "track_url": "/playback/movie/test/subtitles/track/english",
                    },
                ],
            }
        ),
    )
    page.route(
        "**/playback/movie/*/subtitles/track/*",
        lambda route: route.fulfill(
            status=200,
            content_type="text/vtt",
            body="WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nمرحبا\n",
        ),
    )
    page.route(
        "**/playback/movie/*/local",
        lambda route: route.fulfill(
            status=202,
            json={
                "ok": True,
                "session": {
                    "id": "play_browser",
                    "state": "metadata",
                    "message": "Reading torrent metadata…",
                    "buffer_percent": 0,
                },
                "status_url": "/playback/runtime/play_browser",
                "stream_url": None,
                "stop_url": "/playback/runtime/play_browser/stop",
            },
        ),
    )
    page.route(
        "**/playback/runtime/play_browser",
        lambda route: route.fulfill(
            json={
                "ok": True,
                "session": {
                    "state": "ready",
                    "message": "Local stream is ready.",
                    "file_name": "movie.mp4",
                    "stream_url": "http://127.0.0.1:54321/dragon-stream/test/hash/movie.mp4",
                    "buffer_percent": 12,
                    "file_progress": 0.1,
                    "downloaded_bytes": 1048576,
                    "cache_hit": True,
                    "peers": 3,
                    "download_speed": 1048576,
                    "complete": False,
                },
            }
        ),
    )
    page.route(
        "http://127.0.0.1:54321/dragon-stream/**",
        lambda route: route.fulfill(status=206, content_type="video/mp4", body=b""),
    )
    page.route(
        "**/playback/runtime/play_browser/stop",
        lambda route: route.fulfill(json={"ok": True}),
    )

    page.set_viewport_size({"width": 1280, "height": 800})
    sign_in(page, live_app)
    page.goto(f"{live_app}/movies/{movie_id}")
    source = page.get_by_label("Player source")
    assert source.input_value() == "vidsrc"
    assert page.locator("[data-subtitle-select]").count() == 0
    source.select_option(label="Local · FHD")
    assert page.locator("[data-player-badge]").inner_text() == "Local"
    page.get_by_role("button", name="Start local player").click()
    page.locator("[data-movie-player][data-playback-state]").wait_for()
    page.wait_for_function(
        "() => document.querySelector('[data-subtitle-status]')?.textContent"
        ".includes('Arabic · Arabic release is selected')"
    )
    assert page.locator("video track").count() == 0
    assert page.locator("[data-player-video]").evaluate("video => video.controls") is False
    assert page.locator("[data-player-shell]").is_visible()
    assert page.locator("[data-player-netflix-controls]").count() == 1
    assert page.locator("[data-player-caption-toggle]").count() == 1
    assert page.locator("[data-player-timeline]").count() == 1
    page.locator("[data-player-caption-toggle]").click()
    page.locator("[data-player-subtitle-panel]").wait_for(state="visible")
    assert page.locator("[data-player-subtitle-list]").get_by_text("Arabic · Arabic release").count() == 1
    assert page.locator("[data-player-subtitle-list]").get_by_text("English · English release").count() == 1
    page.locator("[data-player-subtitle-list] button").filter(has_text="English · English release").click()
    page.wait_for_function(
        "() => document.querySelector('[data-subtitle-status]')?.textContent"
        ".includes('English · English release is selected')"
    )
    assert page.locator("[data-player-video]").is_visible()
    assert not page.locator("[data-player-frame]").is_visible()

    desktop_layout = page.evaluate(
        """() => {
          const detail = document.querySelector('.movie-detail').getBoundingClientRect();
          const player = document.querySelector('.movie-player').getBoundingClientRect();
          const poster = document.querySelector('.movie-detail__poster').getBoundingClientRect();
          const hero = document
            .querySelector('.movie-detail__content--hero')
            .getBoundingClientRect();
          return {
            detailLeft: detail.left,
            detailWidth: detail.width,
            playerLeft: player.left,
            playerWidth: player.width,
            playerTop: player.top,
            heroBottom: hero.bottom,
            posterBottom: poster.bottom,
          };
        }"""
    )
    assert abs(desktop_layout["playerLeft"] - desktop_layout["detailLeft"]) <= 1
    assert abs(desktop_layout["playerWidth"] - desktop_layout["detailWidth"]) <= 1
    assert desktop_layout["playerTop"] >= max(
        desktop_layout["heroBottom"], desktop_layout["posterBottom"]
    )

    page.set_viewport_size({"width": 390, "height": 844})
    metrics = page.evaluate(
        "() => ({scrollWidth: document.documentElement.scrollWidth, "
        "clientWidth: document.documentElement.clientWidth})"
    )
    assert metrics["scrollWidth"] == metrics["clientWidth"]


def test_failed_subtitle_tracks_stay_visible_and_off_is_explicit(page, live_app, app):
    with app.app_context():
        movie = Movie(
            title="Subtitle State",
            normalized_title="subtitle state",
            external_ids={"imdb_id": "tt2543164"},
        )
        db.session.add(movie)
        db.session.flush()
        db.session.add(
            PlaybackSource(
                movie_id=movie.id,
                kind="magnet",
                label="FHD magnet",
                locator="magnet:?xt=urn:btih:1123456789abcdef0123456789abcdef01234567",
            )
        )
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MAGNETS_ENABLED=True,
        DRAGON_VIDSRC_ENABLED=False,
        DRAGON_SUBTITLES_ENABLED=True,
        DRAGON_SUBDL_API_KEY="private-key",
    )
    subtitle_items = [
        {
            "language": "ar",
            "language_name": "Arabic",
            "label": f"Arabic release {number}",
            "hearing_impaired": False,
            "track_url": f"/playback/movie/test/subtitles/track/arabic-{number}",
        }
        for number in range(1, 4)
    ]
    page.route(
        "**/playback/movie/*/subtitles",
        lambda route: route.fulfill(json={"ok": True, "items": subtitle_items}),
    )
    page.route(
        "**/playback/movie/*/subtitles/track/*",
        lambda route: route.fulfill(
            status=503,
            content_type="text/plain",
            body="Free daily download limit reached (50/day).",
        ),
    )
    page.route(
        "**/playback/movie/*/local",
        lambda route: route.fulfill(
            status=202,
            json={
                "ok": True,
                "session": {"id": "play_subtitle_state", "state": "metadata", "buffer_percent": 0},
                "status_url": "/playback/runtime/play_subtitle_state",
                "stream_url": None,
                "stop_url": "/playback/runtime/play_subtitle_state/stop",
            },
        ),
    )
    page.route(
        "**/playback/runtime/play_subtitle_state",
        lambda route: route.fulfill(
            json={
                "ok": True,
                "session": {
                    "state": "ready",
                    "message": "Local stream is ready.",
                    "file_name": "episode.mp4",
                    "stream_url": "http://127.0.0.1:54321/dragon-stream/test/hash/episode.mp4",
                    "buffer_percent": 100,
                    "file_progress": 1,
                    "downloaded_bytes": 1048576,
                    "cache_hit": True,
                    "peers": 3,
                    "download_speed": 1048576,
                    "complete": False,
                },
            }
        ),
    )
    page.route(
        "http://127.0.0.1:54321/dragon-stream/**",
        lambda route: route.fulfill(status=206, content_type="video/mp4", body=b""),
    )
    page.route(
        "**/playback/runtime/play_subtitle_state/stop",
        lambda route: route.fulfill(json={"ok": True}),
    )

    sign_in(page, live_app)
    page.goto(f"{live_app}/movies/{movie_id}")
    page.get_by_role("button", name="Start local player").click()
    page.wait_for_function(
        "() => document.querySelector('[data-subtitle-status]')?.textContent.includes('limit reached')"
    )
    page.locator("[data-player-caption-toggle]").click()
    options = page.locator("[data-player-subtitle-option]")
    assert options.count() == 4
    assert "is-active" not in (options.nth(0).get_attribute("class") or "")
    assert "has-error" in (options.nth(1).get_attribute("class") or "")
    assert "has-error" in (options.nth(2).get_attribute("class") or "")
    assert "has-error" in (options.nth(3).get_attribute("class") or "")
    assert "is-active" in (options.nth(3).get_attribute("class") or "")

    options.nth(2).click()
    page.wait_for_function(
        "() => document.querySelectorAll('[data-player-subtitle-option]')[2]"
        ".classList.contains('has-error')"
    )
    assert options.count() == 4
    assert "is-active" in (options.nth(2).get_attribute("class") or "")

    options.nth(0).click()
    assert options.count() == 4
    assert "is-active" in (options.nth(0).get_attribute("class") or "")


def test_failed_subtitle_auto_tries_next_available_track(page, live_app, app):
    with app.app_context():
        movie = Movie(
            title="Subtitle Fallback",
            normalized_title="subtitle fallback",
            external_ids={"imdb_id": "tt2543164"},
        )
        db.session.add(movie)
        db.session.flush()
        db.session.add(
            PlaybackSource(
                movie_id=movie.id,
                kind="magnet",
                label="FHD magnet",
                locator="magnet:?xt=urn:btih:2123456789abcdef0123456789abcdef01234567",
            )
        )
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MAGNETS_ENABLED=True,
        DRAGON_VIDSRC_ENABLED=False,
        DRAGON_SUBTITLES_ENABLED=True,
        DRAGON_SUBDL_API_KEY="private-key",
    )
    page.route(
        "**/playback/movie/*/subtitles",
        lambda route: route.fulfill(
            json={
                "ok": True,
                "items": [
                    {
                        "language": "ar",
                        "language_name": "Arabic",
                        "label": "Broken release",
                        "hearing_impaired": False,
                        "track_url": "/playback/movie/test/subtitles/track/broken",
                    },
                    {
                        "language": "ar",
                        "language_name": "Arabic",
                        "label": "Working release",
                        "hearing_impaired": False,
                        "track_url": "/playback/movie/test/subtitles/track/working",
                    },
                ],
            }
        ),
    )

    def handle_track(route):
        if route.request.url.endswith("/broken"):
            route.fulfill(status=503, content_type="text/plain", body="Broken subtitle")
            return
        route.fulfill(
            content_type="text/vtt",
            body="WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nWorking\n",
        )

    page.route("**/playback/movie/*/subtitles/track/*", handle_track)
    page.route(
        "**/playback/movie/*/local",
        lambda route: route.fulfill(
            status=202,
            json={
                "ok": True,
                "session": {"id": "play_subtitle_fallback", "state": "metadata", "buffer_percent": 0},
                "status_url": "/playback/runtime/play_subtitle_fallback",
                "stream_url": None,
                "stop_url": "/playback/runtime/play_subtitle_fallback/stop",
            },
        ),
    )
    page.route(
        "**/playback/runtime/play_subtitle_fallback",
        lambda route: route.fulfill(
            json={
                "ok": True,
                "session": {
                    "state": "ready",
                    "message": "Local stream is ready.",
                    "file_name": "episode.mp4",
                    "stream_url": "http://127.0.0.1:54321/dragon-stream/test/hash/episode.mp4",
                    "buffer_percent": 100,
                    "file_progress": 1,
                    "downloaded_bytes": 1048576,
                    "cache_hit": True,
                    "peers": 3,
                    "download_speed": 1048576,
                    "complete": False,
                },
            }
        ),
    )
    page.route(
        "http://127.0.0.1:54321/dragon-stream/**",
        lambda route: route.fulfill(status=206, content_type="video/mp4", body=b""),
    )
    page.route(
        "**/playback/runtime/play_subtitle_fallback/stop",
        lambda route: route.fulfill(json={"ok": True}),
    )

    sign_in(page, live_app)
    page.goto(f"{live_app}/movies/{movie_id}")
    page.get_by_role("button", name="Start local player").click()
    page.wait_for_function(
        "() => document.querySelector('[data-subtitle-status]')?.textContent.includes('Working release is selected')"
    )
    page.locator("[data-player-caption-toggle]").click()
    options = page.locator("[data-player-subtitle-option]")
    assert "has-error" in (options.nth(1).get_attribute("class") or "")
    assert "is-active" in (options.nth(2).get_attribute("class") or "")


def test_season_pack_player_uses_selected_episode_from_same_pack(page, live_app, app):
    captured = {}
    subtitle_queries = []

    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            external_ids={"tmdb_id": "1399", "tmdb_type": "tv"},
        )
        db.session.add(movie)
        db.session.flush()
        db.session.add(
            PlaybackSource(
                movie_id=movie.id,
                kind="magnet",
                label="S01 season pack Jackett magnet",
                locator="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
                metadata_json={"season_pack": True, "season": 1, "release_mode": "season_pack"},
                selected=True,
            )
        )
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MAGNETS_ENABLED=True,
        DRAGON_VIDSRC_ENABLED=False,
        DRAGON_SUBTITLES_ENABLED=True,
        DRAGON_SUBDL_API_KEY="private-key",
    )
    page.route(
        "**/movies/api/tv/1399/seasons/1/episodes",
        lambda route: route.fulfill(
            json={
                "ok": True,
                "items": [
                    {"episode_number": 1, "name": "Pilot"},
                    {"episode_number": 2, "name": "46 Long"},
                ],
            }
        ),
    )
    def handle_subtitles(route):
        if "/track/" in route.request.url:
            route.fulfill(
                status=200,
                content_type="text/vtt",
                body="WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nمرحبا\n",
            )
            return
        subtitle_queries.append(route.request.url)
        route.fulfill(
            json={
                "ok": True,
                "items": [
                    {
                        "language": "ar",
                        "language_name": "Arabic",
                        "label": "Season 1 Arabic",
                        "hearing_impaired": False,
                        "track_url": "/playback/movie/test/subtitles/track/arabic-s01e02",
                    }
                ],
            }
        )

    page.route("**/playback/movie/*/subtitles**", handle_subtitles)

    def handle_local(route):
        captured.update(route.request.post_data_json)
        route.fulfill(
            status=202,
            json={
                "ok": True,
                "session": {
                    "id": "play_pack",
                    "state": "metadata",
                    "message": "Reading torrent metadata…",
                    "buffer_percent": 0,
                },
                "status_url": "/playback/runtime/play_pack",
                "stream_url": None,
                "stop_url": "/playback/runtime/play_pack/stop",
            },
        )

    page.route("**/playback/movie/*/local", handle_local)
    page.route(
        "**/playback/runtime/play_pack",
        lambda route: route.fulfill(
            json={
                "ok": True,
                "session": {
                    "state": "ready",
                    "message": "Local stream is ready.",
                    "file_name": "The.Sopranos.S01E02.mp4",
                    "stream_url": "http://127.0.0.1:54321/dragon-stream/test/hash/episode.mp4",
                    "buffer_percent": 12,
                    "file_progress": 0.1,
                    "downloaded_bytes": 1048576,
                    "cache_hit": True,
                    "peers": 3,
                    "download_speed": 1048576,
                    "complete": False,
                },
            }
        ),
    )
    page.route(
        "http://127.0.0.1:54321/dragon-stream/**",
        lambda route: route.fulfill(status=206, content_type="video/mp4", body=b""),
    )
    page.route(
        "**/playback/runtime/play_pack/stop",
        lambda route: route.fulfill(json={"ok": True}),
    )

    sign_in(page, live_app)
    page.goto(f"{live_app}/movies/{movie_id}")
    page.locator("[data-player-pack-browser]").wait_for()
    assert "Choose an episode from this pack" not in page.content()
    assert "Season 1 pack" not in page.content()
    assert "SEASON PACK" not in page.content()
    page.locator("[data-player-pack-episode] option[value='2']").wait_for(state="attached")
    page.locator("[data-player-pack-episode]").select_option("2")
    page.get_by_role("button", name="Play selected episode from pack").click()
    page.locator("[data-movie-player][data-playback-state]").wait_for()
    assert captured == {"source_id": captured["source_id"], "season": 1, "episode": 2}
    page.wait_for_function(
        "() => document.querySelector('[data-subtitle-status]')?.textContent"
        ".includes('Arabic · Season 1 Arabic is selected')"
    )
    assert any(
        "season=1" in url and "episode=2" in url and "episode_title=46+Long" in url
        for url in subtitle_queries
    )


def test_switching_from_season_pack_to_regular_local_hides_pack_browser(page, live_app, app):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            external_ids={"tmdb_id": "1399", "tmdb_type": "tv"},
        )
        db.session.add(movie)
        db.session.flush()
        db.session.add_all(
            [
                PlaybackSource(
                    movie_id=movie.id,
                    kind="magnet",
                    label="S01 season pack Jackett magnet",
                    locator="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
                    metadata_json={"season_pack": True, "season": 1, "release_mode": "season_pack"},
                    selected=True,
                ),
                PlaybackSource(
                    movie_id=movie.id,
                    kind="magnet",
                    label="FHD magnet",
                    locator="magnet:?xt=urn:btih:89abcdef012345670123456789abcdef01234567",
                ),
            ]
        )
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MAGNETS_ENABLED=True,
        DRAGON_VIDSRC_ENABLED=False,
        DRAGON_SUBTITLES_ENABLED=True,
        DRAGON_SUBDL_API_KEY="private-key",
    )

    def handle_episodes(route):
        time.sleep(0.2)
        route.fulfill(
            json={
                "ok": True,
                "items": [
                    {"episode_number": 1, "name": "Pilot"},
                    {"episode_number": 2, "name": "46 Long"},
                ],
            }
        )

    page.route("**/movies/api/tv/1399/seasons/1/episodes", handle_episodes)

    sign_in(page, live_app)
    page.goto(f"{live_app}/movies/{movie_id}")
    page.get_by_label("Player source").select_option(label="Local · FHD")
    page.wait_for_timeout(400)
    assert page.locator("[data-player-pack-browser]").is_hidden()
    assert page.locator("[data-subtitle-status]").is_visible()
