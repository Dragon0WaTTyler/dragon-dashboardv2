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


def test_movie_player_switches_between_vidsrc_and_local_without_overflow(
    page, live_app, app
):
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
                locator=(
                    "magnet:?xt=urn:btih:0123456789abcdef"
                    "0123456789abcdef01234567"
                ),
            )
        )
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MAGNETS_ENABLED=True,
        DRAGON_VIDSRC_ENABLED=True,
    )
    page.route(
        "**/playback/movie/*/local",
        lambda route: route.fulfill(
            status=202,
            json={
                "ok": True,
                "session": {
                    "id": "play_browser",
                    "state": "preparing",
                    "message": "Reading torrent metadata…",
                    "buffer_percent": 0,
                },
                "status_url": "/playback/runtime/play_browser",
                "stream_url": "/playback/runtime/play_browser/stream",
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
                    "buffer_percent": 1.2,
                    "peers": 3,
                    "download_speed": 1048576,
                    "complete": False,
                },
            }
        ),
    )
    page.route(
        "**/playback/runtime/play_browser/stream",
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
    source.select_option(label="Local · FHD")
    assert page.locator("[data-player-badge]").inner_text() == "Local"
    page.get_by_role("button", name="Start local player").click()
    page.get_by_text("Local stream is ready.", exact=False).wait_for()
    assert page.locator("[data-player-video]").is_visible()
    assert not page.locator("[data-player-frame]").is_visible()

    page.set_viewport_size({"width": 390, "height": 844})
    metrics = page.evaluate(
        "() => ({scrollWidth: document.documentElement.scrollWidth, "
        "clientWidth: document.documentElement.clientWidth})"
    )
    assert metrics["scrollWidth"] == metrics["clientWidth"]
