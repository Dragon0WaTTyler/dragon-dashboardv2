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
    page.locator("video track[srclang='en']").wait_for(state="attached")
    assert page.locator("video track").count() == 2
    assert page.locator("video track").evaluate_all(
        "tracks => tracks.map(track => ({label: track.label, "
        "language: track.srclang, isDefault: track.default}))"
    ) == [
        {"label": "Arabic · Arabic release", "language": "ar", "isDefault": True},
        {"label": "English · English release", "language": "en", "isDefault": False},
    ]
    assert page.locator("video track[srclang='ar']").count() == 1
    assert page.locator("[data-player-video]").evaluate("video => video.controls") is True
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
