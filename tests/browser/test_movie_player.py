from pathlib import Path

import pytest

from app.extensions import db
from app.movies.models import Movie, MovieProgress
from app.playback.models import PlaybackSource
from app.playback.services import PlaybackService

pytestmark = pytest.mark.browser


def _art(label: str, start: str, end: str) -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="960">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop stop-color="{start}"/><stop offset="1" stop-color="{end}"/>'
        f'</linearGradient></defs><rect width="100%" height="100%" fill="url(%23g)"/>'
        f'<text x="48" y="820" fill="white" font-size="42">{label}</text></svg>'
    )
    return "data:image/svg+xml," + svg.replace("#", "%23").replace(" ", "%20")


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
            body=(
                "WEBVTT\n\n"
                "00:00:01.000 --> 00:00:03.000\n"
                '<font color="#ffff00">لتكوني في تي سي بي</font>\n'
                "واي يوغرت\n"
                "عند وصول المدير\n"
                "\n"
                "00:00:04.000 --> 00:00:05.000\n"
                "حسنا\n"
            ),
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
    ambient_root = page.locator(".movies-v2[data-ambient-level]")
    assert ambient_root.get_attribute("data-ambient-level") == "subtle"
    assert ambient_root.get_attribute("data-reduced-effects") == "false"
    assert ambient_root.evaluate(
        "node => getComputedStyle(node).getPropertyValue('--movie-ambient-strength').trim()"
    ) == ".32"
    page.emulate_media(reduced_motion="reduce")
    assert ambient_root.evaluate(
        "node => getComputedStyle(node).getPropertyValue('--movie-ambient-strength').trim()"
    ) == ".14"
    page.emulate_media(reduced_motion="no-preference")
    assert page.get_by_role("link", name="Provider settings").count() == 0
    assert page.locator("[data-subtitle-status]").is_hidden()
    page.set_viewport_size({"width": 390, "height": 844})
    player = page.locator("[data-movie-player]")
    player.evaluate("element => element.classList.add('is-watch-mode')")
    watch_mode_metrics = player.evaluate(
        """element => {
          const viewport = element.querySelector('.movie-player__viewport').getBoundingClientRect();
          return {
            viewportWidth: viewport.width,
            viewportHeight: viewport.height,
            pageWidth: document.documentElement.clientWidth,
            pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          };
        }"""
    )
    assert watch_mode_metrics["viewportHeight"] == pytest.approx(
        watch_mode_metrics["viewportWidth"] * 9 / 16,
        abs=2,
    )
    assert watch_mode_metrics["viewportWidth"] <= watch_mode_metrics["pageWidth"]
    assert watch_mode_metrics["pageOverflow"] == 0
    player.evaluate("element => element.classList.remove('is-watch-mode')")
    page.set_viewport_size({"width": 1280, "height": 800})
    idle_viewport = page.locator("[data-movie-player] .movie-player__viewport").bounding_box()
    assert idle_viewport is not None
    assert 250 <= idle_viewport["height"] <= 380
    source = page.get_by_label("Player source")
    assert source.input_value() == "vidsrc"
    assert page.locator("[data-player-source-choice]").count() == 0
    source.select_option(label="Local · FHD")
    page.wait_for_function(
        "() => document.querySelector('[data-player-source]')?.selectedOptions[0]?.dataset.kind"
        " === 'local'"
    )
    assert page.locator("[data-subtitle-select]").count() == 0
    assert page.locator("[data-player-badge]").inner_text() == "Local"
    assert page.get_by_text(
        "Local selected. Playback starts only when you press play.", exact=True
    ).is_visible()
    page.get_by_role("button", name="Start local player").click()
    page.locator("[data-movie-player][data-playback-state]").wait_for()
    page.wait_for_function(
        "() => document.querySelector('[data-subtitle-status]')?.textContent"
        ".includes('Arabic · Arabic release is selected')"
    )
    assert page.locator("video track").count() == 0
    assert page.locator("[data-player-video]").evaluate("video => video.controls") is False
    assert page.locator("[data-player-shell]").is_visible()
    assert page.locator("[data-player-dragon-controls]").count() == 1
    assert page.locator("[data-player-caption-toggle]").count() == 1
    assert page.locator("[data-player-timeline]").count() == 1
    page.locator("[data-player-shell]").evaluate(
        "node => node.dispatchEvent(new WheelEvent('wheel', "
        "{ bubbles: true, cancelable: true, deltaY: 100 }))"
    )
    assert page.locator("[data-player-video]").evaluate("video => video.volume") == pytest.approx(
        0.95
    )
    assert (
        page.locator("[data-player-dragon-controls]").evaluate(
            "node => getComputedStyle(node).opacity"
        )
        == "1"
    )
    page.locator("[data-player-shell]").evaluate(
        "node => { node.dataset.controlsVisible = 'false'; }"
    )
    page.locator("[data-player-shell]").hover()
    page.wait_for_function(
        "() => document.querySelector('[data-player-shell]')?.dataset.controlsVisible === 'true'"
    )
    assert (
        page.locator("[data-player-dragon-controls]").evaluate(
            "node => getComputedStyle(node).opacity"
        )
        == "1"
    )
    page.locator("[data-player-video]").evaluate(
        "video => { video.currentTime = 1.5; video.dispatchEvent(new Event('timeupdate')); }"
    )
    page.wait_for_function(
        "() => document.querySelector('[data-movie-player]')?.dataset.captionLanguage === 'ar'"
    )
    assert page.locator("[data-player-caption-text]").evaluate("node => node.dir") == "rtl"
    assert (
        page.locator("[data-player-caption-text]").evaluate(
            "node => getComputedStyle(node).textAlign"
        )
        == "center"
    )
    assert (
        page.locator("[data-player-caption-text]").evaluate("node => node.childElementCount") == 2
    )
    normalized_caption = page.locator("[data-player-caption-text]").evaluate(
        "node => Array.from(node.children).map((child) => child.textContent).join(' ')"
        ".replace(/[\\u200E\\u200F\\u2066-\\u2069]/g, '')"
        ".replace(/\\u00a0/g, ' ')"
    )
    assert "لتكوني في تي سي بي واي يوغرت عند وصول المدير" in normalized_caption
    assert "<font" not in normalized_caption.lower()
    page.locator("[data-player-caption-toggle]").click()
    page.locator("[data-player-subtitle-panel]").wait_for(state="visible")
    subtitle_list = page.locator("[data-player-subtitle-list]")
    assert subtitle_list.get_by_text("Arabic · Arabic release").count() == 1
    assert subtitle_list.get_by_text("English · English release").count() == 1
    page.get_by_role("button", name="Appearance").click()
    page.locator("[data-player-subtitle-size]").evaluate(
        "node => { node.value = '44'; node.dispatchEvent(new Event('input', { bubbles: true })); }"
    )
    page.locator("[data-player-video]").evaluate(
        "video => { video.currentTime = 1.5; video.dispatchEvent(new Event('timeupdate')); }"
    )
    arabic_line_metrics = page.locator("[data-player-caption-text]").evaluate(
        """node => Array.from(node.children).map((line) => ({
          scrollWidth: line.scrollWidth,
          clientWidth: line.clientWidth,
          whiteSpace: getComputedStyle(line).whiteSpace,
        }))"""
    )
    assert len(arabic_line_metrics) == 2
    assert all(metric["whiteSpace"] == "nowrap" for metric in arabic_line_metrics)
    assert all(metric["scrollWidth"] <= metric["clientWidth"] + 1 for metric in arabic_line_metrics)
    page.locator("[data-player-subtitle-size]").evaluate(
        "node => { node.value = '48'; node.dispatchEvent(new Event('input', { bubbles: true })); }"
    )
    medium_caption_size = page.locator("[data-player-caption-text]").evaluate(
        "node => Number.parseFloat(getComputedStyle(node).fontSize)"
    )
    page.locator("[data-player-subtitle-size]").evaluate(
        "node => { node.value = '65'; node.dispatchEvent(new Event('input', { bubbles: true })); }"
    )
    assert page.locator("[data-player-caption-text]").evaluate(
        "node => Number.parseFloat(getComputedStyle(node).fontSize)"
    ) == pytest.approx(65, abs=0.1)
    assert (
        page.locator("[data-player-caption-text]").evaluate("node => node.childElementCount") == 2
    )
    assert page.locator("[data-player-subtitle-size-label]").inner_text() == "65px"
    large_line_metrics = page.locator("[data-player-caption-text]").evaluate(
        """node => Array.from(node.children).map((line) => ({
          scrollWidth: line.scrollWidth,
          clientWidth: line.clientWidth,
        }))"""
    )
    assert all(metric["scrollWidth"] <= metric["clientWidth"] + 1 for metric in large_line_metrics)
    caption_safe_area = page.locator("[data-player-captions]").evaluate(
        """node => {
          const shell = node.closest('[data-player-shell]');
          return {
            captionBottom: node.getBoundingClientRect().bottom,
            shellBottom: shell.getBoundingClientRect().bottom,
          };
        }"""
    )
    assert caption_safe_area["shellBottom"] - caption_safe_area["captionBottom"] >= 95
    page.locator("[data-player-subtitle-size]").evaluate(
        "node => { node.value = '96'; node.dispatchEvent(new Event('input', { bubbles: true })); }"
    )
    large_caption_size = page.locator("[data-player-caption-text]").evaluate(
        "node => Number.parseFloat(getComputedStyle(node).fontSize)"
    )
    assert large_caption_size == pytest.approx(96, abs=0.1)
    assert large_caption_size > medium_caption_size + 4
    assert (
        page.locator("[data-player-caption-text]").evaluate("node => node.childElementCount") == 2
    )
    maximum_size_line_metrics = page.locator("[data-player-caption-text]").evaluate(
        """node => Array.from(node.children).map((line) => ({
          scrollWidth: line.scrollWidth,
          clientWidth: line.clientWidth,
        }))"""
    )
    assert all(
        metric["scrollWidth"] <= metric["clientWidth"] + 1 for metric in maximum_size_line_metrics
    )
    long_caption_size = page.locator("[data-player-caption-text]").evaluate(
        "node => getComputedStyle(node).fontSize"
    )
    page.locator("[data-player-video]").evaluate(
        "video => { video.currentTime = 3.5; video.dispatchEvent(new Event('timeupdate')); }"
    )
    assert page.locator("[data-player-captions]").is_hidden()
    page.locator("[data-player-video]").evaluate(
        "video => { video.currentTime = 4.5; video.dispatchEvent(new Event('timeupdate')); }"
    )
    short_caption_size = page.locator("[data-player-caption-text]").evaluate(
        "node => getComputedStyle(node).fontSize"
    )
    assert short_caption_size == long_caption_size
    page.get_by_role("button", name="Back to subtitles").click()
    subtitle_list.locator("button").filter(has_text="English · English release").click()
    page.wait_for_function(
        "() => document.querySelector('[data-subtitle-status]')?.textContent"
        ".includes('English · English release is selected')"
    )
    page.get_by_role("button", name="Appearance").click()
    page.locator("[data-player-subtitle-preset]").select_option("Minimal")
    page.locator("[data-player-subtitle-background]").select_option("Off")
    page.locator("[data-player-subtitle-position]").evaluate(
        "node => { node.value = '40'; node.dispatchEvent(new Event('input', { bubbles: true })); }"
    )
    assert page.locator("[data-player-subtitle-size]").get_attribute("max") == "96"
    page.locator("[data-player-subtitle-size]").evaluate(
        "node => { node.value = '84'; node.dispatchEvent(new Event('input', { bubbles: true })); }"
    )
    page.locator("[data-player-subtitle-shadow]").evaluate(
        "node => { node.value = '35'; node.dispatchEvent(new Event('input', { bubbles: true })); }"
    )
    page.locator("[data-player-subtitle-font]").select_option("Cairo")
    caption_background = page.locator("[data-movie-player]").evaluate(
        "node => node.dataset.captionBackground"
    )
    assert caption_background == "off"
    stored_style = page.evaluate(
        "() => JSON.parse(localStorage.getItem('dragon:subtitle-style:v2:en'))"
    )
    assert stored_style["background"] == "off"
    assert stored_style["size"] == 84
    assert stored_style["position"] == 40
    assert stored_style["shadow"] == 35
    assert stored_style["font"] == "cairo"
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
    # Detail heroes are edge-to-edge; player and secondary modules retain the
    # Movies safe-area inset for readable controls and source metadata.
    assert 0 < desktop_layout["playerLeft"] - desktop_layout["detailLeft"] <= 64
    assert desktop_layout["playerWidth"] < desktop_layout["detailWidth"]
    assert desktop_layout["playerTop"] >= max(
        desktop_layout["heroBottom"], desktop_layout["posterBottom"]
    )

    # Changing sources while a local runtime is active must not wait for its shutdown.
    source.select_option("vidsrc")
    page.wait_for_function(
        "() => document.querySelector('[data-player-source]')?.value === 'vidsrc'"
        " && document.querySelector('[data-player-badge]')?.textContent === 'VidSrc'"
        " && !document.querySelector('[data-movie-player]')?.classList.contains('is-watch-mode')"
    )
    assert page.get_by_role("button", name="Play with VidSrc").is_visible()

    page.set_viewport_size({"width": 390, "height": 844})
    metrics = page.evaluate(
        "() => ({scrollWidth: document.documentElement.scrollWidth, "
        "clientWidth: document.documentElement.clientWidth})"
    )
    assert metrics["scrollWidth"] == metrics["clientWidth"]


def test_movie_player_switches_between_authorized_embeds(page, live_app, app):
    with app.app_context():
        movie = Movie(
            title="Embed Switch",
            normalized_title="embed switch",
            external_ids={"imdb_id": "tt2543164"},
        )
        db.session.add(movie)
        db.session.commit()
        source = PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="videotube",
            provider_asset_id="iuki4kda2u7l",
            label="VideoTube · Arabic",
            subtitle_languages=["ar"],
        )
        updown = PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="updown",
            provider_asset_id="updownasset",
            label="UpDown",
        )
        ok = PlaybackService.upsert_indexed_embed_source(
            movie_id=movie.id,
            provider="ok",
            provider_asset_id="7593181055685",
            label="OK.ru",
        )
        movie_id = movie.id
        source_id = source.id
        updown_id = updown.id
        ok_id = ok.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_VIDSRC_ENABLED=True,
        DRAGON_VIDEOTUBE_ENABLED=True,
        DRAGON_VIDEOTUBE_EMBED_URL="https://down.vidtube.one/embed-{asset_id}.html",
        DRAGON_UPDOWN_ENABLED=True,
        DRAGON_UPDOWN_EMBED_URL="https://updown.icu/embed-{asset_id}-1280x640.html",
        DRAGON_OK_ENABLED=True,
        DRAGON_OK_EMBED_URL="https://ok.ru/videoembed/{asset_id}",
    )

    page.route(
        f"**/playback/movie/{movie_id}/vidsrc",
        lambda route: route.fulfill(
            json={
                "ok": True,
                "source": {
                    "provider": "vidsrc",
                    "label": "VidSrc",
                    "url": "https://embed.vidsrc.example/tt2543164",
                    "match": "imdb",
                },
            }
        ),
    )
    page.route(
        f"**/playback/movie/{movie_id}/sources/{source_id}/embed",
        lambda route: route.fulfill(
            json={
                "ok": True,
                "source": {
                    "provider": "videotube",
                    "label": "VideoTube",
                    "url": "https://down.vidtube.one/embed-iuki4kda2u7l.html",
                    "match": "indexed",
                    "sandbox": "allow-scripts allow-forms allow-popups allow-presentation",
                },
            }
        ),
    )
    page.route(
        f"**/playback/movie/{movie_id}/sources/{updown_id}/embed",
        lambda route: route.fulfill(
            json={
                "ok": True,
                "source": {
                    "provider": "updown",
                    "label": "UpDown",
                    "url": "https://updown.icu/embed-updownasset-1280x640.html",
                    "match": "indexed",
                    "sandbox": "allow-scripts allow-forms allow-popups allow-presentation",
                },
            }
        ),
    )
    page.route(
        f"**/playback/movie/{movie_id}/sources/{ok_id}/embed",
        lambda route: route.fulfill(
            json={
                "ok": True,
                "source": {
                    "provider": "ok",
                    "label": "OK.ru",
                    "url": "https://ok.ru/videoembed/7593181055685",
                    "match": "indexed",
                    "sandbox": "allow-scripts allow-forms allow-popups allow-presentation",
                },
            }
        ),
    )

    provider_requests = []
    provider_hosts = ("down.vidtube.one", "updown.icu", "ok.ru")
    page.on(
        "request",
        lambda request: provider_requests.append(request.url)
        if any(host in request.url for host in provider_hosts)
        else None,
    )
    sign_in(page, live_app)
    page.goto(f"{live_app}/movies/{movie_id}")
    source_select = page.get_by_label("Player source")
    assert source_select.input_value() == source_id
    assert provider_requests == []
    assert page.locator("[data-player-source-choice]").count() == 0

    assert page.locator("[data-player-badge]").inner_text() == "VideoTube · Arabic"
    page.get_by_role("button", name="Play with VideoTube · Arabic").click()
    frame = page.locator("[data-player-frame]")
    frame.wait_for(state="visible")
    page.wait_for_function(
        "() => document.querySelector('[data-player-frame]')?.src === 'https://down.vidtube.one/embed-iuki4kda2u7l.html'"
    )
    assert (
        frame.get_attribute("sandbox")
        == "allow-scripts allow-forms allow-popups allow-presentation"
    )
    assert frame.get_attribute("title") == "VideoTube · Arabic player"
    assert page.get_by_role("link", name="Open separately").is_visible()
    assert page.get_by_role("button", name="Change source").count() == 0
    assert page.get_by_role("button", name="Full screen").count() == 0
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(100)
    assert page.locator("[data-player-external-toolbar]").bounding_box()["width"] < 190
    assert page.get_by_role("link", name="Open separately").bounding_box()["width"] < 170

    source_select.select_option(updown_id)
    page.wait_for_function(
        "() => document.querySelector('[data-player-badge]')?.textContent === 'UpDown'"
    )
    assert source_select.input_value() == updown_id
    page.get_by_role("button", name="Play with UpDown").click()
    page.wait_for_function(
        "() => document.querySelector('[data-player-frame]')?.src === 'https://updown.icu/embed-updownasset-1280x640.html'"
    )

    source_select.select_option(ok_id)
    page.wait_for_function(
        "() => document.querySelector('[data-player-badge]')?.textContent === 'OK.ru'"
    )
    assert source_select.input_value() == ok_id
    page.get_by_role("button", name="Play with OK.ru").click()
    page.wait_for_function(
        "() => document.querySelector('[data-player-frame]')?.src === 'https://ok.ru/videoembed/7593181055685'"
    )

    source_select.select_option("vidsrc")
    page.wait_for_function(
        "() => document.querySelector('[data-player-badge]')?.textContent === 'VidSrc'"
    )
    assert source_select.input_value() == "vidsrc"
    assert frame.get_attribute("src") == "about:blank"
    page.get_by_role("button", name="Play with VidSrc").click()
    page.wait_for_function(
        "() => document.querySelector('[data-player-frame]')?.src === 'https://embed.vidsrc.example/tt2543164'"
    )
    assert frame.get_attribute("sandbox") is None


def test_movie_player_offers_resume_from_saved_progress(page, live_app, app):
    with app.app_context():
        movie = Movie(
            title="Resume Film",
            normalized_title="resume film",
            runtime_minutes=100,
        )
        db.session.add(movie)
        db.session.flush()
        db.session.add(
            PlaybackSource(
                movie_id=movie.id,
                kind="magnet",
                label="FHD magnet",
                locator="magnet:?xt=urn:btih:3123456789abcdef0123456789abcdef01234567",
            )
        )
        db.session.add(
            MovieProgress(
                movie_id=movie.id,
                current_seconds=2530,
                duration_seconds=6000,
                completed=False,
            )
        )
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MAGNETS_ENABLED=True,
        DRAGON_VIDSRC_ENABLED=False,
    )

    sign_in(page, live_app)
    page.goto(f"{live_app}/movies/{movie_id}")
    page.get_by_role("button", name="Resume from 42:10").wait_for()


def test_movie_player_refreshes_resume_point_after_saving_progress(page, live_app, app):
    with app.app_context():
        movie = Movie(
            title="Resume Refresh",
            normalized_title="resume refresh",
            runtime_minutes=100,
        )
        db.session.add(movie)
        db.session.flush()
        db.session.add(
            PlaybackSource(
                movie_id=movie.id,
                kind="magnet",
                label="FHD magnet",
                locator="magnet:?xt=urn:btih:4123456789abcdef0123456789abcdef01234567",
            )
        )
        db.session.add(
            MovieProgress(
                movie_id=movie.id,
                current_seconds=929,
                duration_seconds=6000,
                completed=False,
            )
        )
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MAGNETS_ENABLED=True,
        DRAGON_VIDSRC_ENABLED=False,
    )
    local_requests = []

    def handle_local(route):
        local_requests.append(route.request.post_data_json)
        route.fulfill(
            status=202,
            json={
                "ok": True,
                "session": {
                    "id": "play_resume_refresh",
                    "state": "metadata",
                    "message": "Reading torrent metadata…",
                    "buffer_percent": 0,
                },
                "status_url": "/playback/runtime/play_resume_refresh",
                "stream_url": None,
                "stop_url": "/playback/runtime/play_resume_refresh/stop",
            },
        )

    page.route("**/playback/movie/*/local", handle_local)
    page.route(
        "**/playback/runtime/play_resume_refresh",
        lambda route: route.fulfill(
            json={
                "ok": True,
                "session": {
                    "state": "ready",
                    "message": "Local stream is ready.",
                    "file_name": "resume.mp4",
                    "stream_url": "http://127.0.0.1:54321/dragon-stream/test/hash/resume.mp4",
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
        "**/playback/runtime/play_resume_refresh/stop",
        lambda route: route.fulfill(json={"ok": True}),
    )

    sign_in(page, live_app)
    page.goto(f"{live_app}/movies/{movie_id}")
    page.get_by_role("button", name="Resume from 15:29").wait_for()
    page.get_by_role("button", name="Resume from 15:29").click()
    page.locator("[data-movie-player][data-playback-state]").wait_for()
    assert local_requests[0]["resumeSeconds"] == 929

    page.locator("[data-player-video]").evaluate(
        "video => { video.dispatchEvent(new Event('loadedmetadata')); video.currentTime = 2583; "
        "video.dispatchEvent(new Event('timeupdate')); video.dispatchEvent(new Event('pause')); }"
    )
    page.get_by_role("button", name="Stop local stream").click()
    page.get_by_role("button", name="Resume from 43:03").wait_for()
    page.get_by_role("button", name="Resume from 43:03").click()
    page.wait_for_timeout(200)
    assert local_requests[1]["resumeSeconds"] == 2583


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
        "() => document.querySelector('[data-subtitle-status]')?.textContent"
        ".includes('limit reached')"
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
                "session": {
                    "id": "play_subtitle_fallback",
                    "state": "metadata",
                    "buffer_percent": 0,
                },
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
        "() => document.querySelector('[data-subtitle-status]')?.textContent"
        ".includes('Working release is selected')"
    )
    page.locator("[data-player-caption-toggle]").click()
    options = page.locator("[data-player-subtitle-option]")
    assert "has-error" in (options.nth(1).get_attribute("class") or "")
    assert "is-active" in (options.nth(2).get_attribute("class") or "")


def test_season_pack_player_uses_selected_episode_from_same_pack(page, live_app, app):
    captured = {}
    subtitle_queries = []
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    evidence_dir = Path(r"C:\Users\walid\Pictures\movies-v2-phase1")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    unified_dir = Path(r"C:\Users\walid\Pictures\movies-v2-unified-detail")
    unified_dir.mkdir(parents=True, exist_ok=True)
    closure_dir = Path(r"C:\Users\walid\Pictures\movies-v2-library-closure")
    closure_dir.mkdir(parents=True, exist_ok=True)

    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            poster_url=_art("SOPRANOS", "#17283d", "#b9454f"),
            external_ids={"tmdb_id": "1399", "tmdb_type": "tv"},
            metadata_state={
                "tmdb_detail": {
                    "backdrop_url": _art("REACTOR", "#111d2b", "#5c2839"),
                },
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
        db.session.flush()
        db.session.add(
            PlaybackSource(
                movie_id=movie.id,
                kind="magnet",
                label="S01 season pack Jackett magnet",
                locator="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
                season=1,
                episode=None,
                source_role="season_pack_fallback",
                metadata_json={"season_pack": True, "season": 1, "release_mode": "season_pack"},
                selected=True,
            )
        )
        db.session.add(
            MovieProgress(
                movie=movie,
                season=1,
                episode=1,
                current_seconds=1800,
                duration_seconds=3600,
                completed=False,
            )
        )
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MAGNETS_ENABLED=True,
        DRAGON_JACKETT_ENABLED=True,
        DRAGON_VIDSRC_ENABLED=False,
        DRAGON_MULTIEMBED_ENABLED=False,
        DRAGON_MULTIEMBED_VIP_ENABLED=False,
        DRAGON_SUBTITLES_ENABLED=True,
        DRAGON_SUBDL_API_KEY="private-key",
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
    page.route(
        "**/movies/api/tv/1399/seasons/1/episodes",
        lambda route: route.fulfill(
            json={
                "ok": True,
                "items": [
                    {
                        "episode_number": 1,
                        "name": "Pilot",
                        "runtime_minutes": 60,
                    },
                    {
                        "episode_number": 2,
                        "name": "46 Long",
                        "runtime_minutes": 60,
                    },
                ],
            }
        ),
    )
    page.route(
        "**/movies/api/releases**",
        lambda route: route.fulfill(
            json={
                "ok": True,
                "items": [
                    {
                        "title": "The Sopranos Season 1 Complete 1080p",
                        "magnet_uri": (
                            "magnet:?xt=urn:btih:fedcba9876543210"
                            "fedcba9876543210fedcba98"
                        ),
                        "tracker": "Jackett",
                        "seeders": 42,
                        "size": 5_000_000_000,
                    }
                ],
            }
        ),
    )

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
    page.set_viewport_size({"width": 1600, "height": 844})
    page.goto(f"{live_app}/movies/{movie_id}")
    page.locator(".tv-series-hero").wait_for()
    page.locator("#tv-season-episodes").wait_for()
    assert page.get_by_role("heading", name="Pilot").is_visible()
    page.screenshot(path=str(evidence_dir / "Y-series-detail-hero.png"), full_page=True)
    page.screenshot(path=str(evidence_dir / "J-series-detail-1600.png"), full_page=False)
    page.screenshot(path=str(unified_dir / "D-local-series-hero-1600.png"), full_page=False)
    page.screenshot(path=str(unified_dir / "O-local-series-fullbleed-1600.png"), full_page=False)
    page.locator(".tv-season-summary").screenshot(
        path=str(unified_dir / "E-local-series-resume-1600.png")
    )
    page.locator(".tv-series-seasons").screenshot(path=str(evidence_dir / "Z-series-seasons.png"))
    page.locator(".tv-series-seasons").screenshot(
        path=str(evidence_dir / "K-season-workspace-1600.png")
    )
    page.locator(".tv-series-seasons").screenshot(
        path=str(unified_dir / "F-local-series-season-selector-1600.png")
    )
    page.locator(".tv-series-episode-preview").screenshot(
        path=str(unified_dir / "G-local-series-episodes-1600.png")
    )
    page.screenshot(path=str(closure_dir / "L-season-page.png"), full_page=False)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )
    page.screenshot(path=str(evidence_dir / "AH-series-detail-mobile.png"), full_page=True)
    page.screenshot(path=str(evidence_dir / "P-series-390.png"), full_page=False)
    page.set_viewport_size({"width": 1600, "height": 844})
    page.goto(f"{live_app}/movies/{movie_id}/seasons/1/episodes/2#episode-player")
    season_hero = page.locator(".movie-season-detail__hero")
    season_hero.wait_for()
    assert season_hero.locator(".movie-detail__backdrop.movie-discover-hero__art").count() == 1
    assert season_hero.locator(".movie-player").count() == 0
    assert season_hero.evaluate(
        """hero => {
            const backdrop = hero.querySelector('.movie-detail__backdrop');
            return {
                minHeight: getComputedStyle(hero).minHeight,
                backdropOpacity: getComputedStyle(backdrop).opacity,
                backdropMask: getComputedStyle(backdrop).maskImage,
                heroBefore: getComputedStyle(hero, '::before').display,
                backdropAfter: getComputedStyle(backdrop, '::after').display,
            };
        }"""
    ) == {
        "minHeight": "760px",
        "backdropOpacity": "1",
        "backdropMask": "none",
        "heroBefore": "none",
        "backdropAfter": "none",
    }
    release_browser = page.locator("[data-inline-release-browser]")
    release_browser.wait_for()
    release_browser.evaluate("element => { element.open = true; }")
    page.screenshot(path=str(evidence_dir / "AA-season-page.png"), full_page=True)
    page.screenshot(path=str(evidence_dir / "K-season-page-1600.png"), full_page=False)
    page.screenshot(path=str(unified_dir / "H-local-season-page-1600.png"), full_page=False)
    page.locator(".tv-episode-grid").screenshot(path=str(evidence_dir / "AB-episode-cards.png"))
    assert release_browser.get_by_role("button", name="Find full-season packs").is_visible()
    assert release_browser.locator("[data-season-select]").input_value() == "1"
    assert release_browser.locator("[data-season-select]").is_disabled()
    page.wait_for_function(
        "() => document.querySelector("
        "'[data-inline-release-browser] [data-episode-select]'"
        ")?.options.length > 1"
    )
    release_browser.get_by_role("button", name="Find full-season packs").click()
    release_browser.get_by_role(
        "heading", name="The Sopranos Season 1 Complete 1080p"
    ).wait_for(state="visible")
    assert release_browser.get_by_role("button", name="Add full-season pack").is_visible()
    pack_browser = page.locator("[data-player-pack-browser]")
    pack_browser.wait_for()
    page.wait_for_function(
        "() => document.querySelector('[data-player-pack-episode]')?.options.length > 1"
    )
    assert pack_browser.count() == 1
    assert pack_browser.is_visible()
    assert page.locator("[data-player-pack-episode]").input_value() == "2"
    detail_box = page.locator(".movie-detail").bounding_box()
    secondary_box = page.locator(".movie-detail__content--secondary").bounding_box()
    assert detail_box and secondary_box
    assert secondary_box["x"] <= detail_box["x"] + 80
    assert secondary_box["width"] >= detail_box["width"] - 140
    page.locator("[data-player-launch]").wait_for()
    page.screenshot(path=str(evidence_dir / "AC-episode-context.png"), full_page=True)
    page.locator(".movie-player").screenshot(path=str(closure_dir / "M-episode-deep-link.png"))
    page.screenshot(
        path=str(closure_dir / "J-series-episode-player-deep-link.png"), full_page=False
    )
    page.locator("[data-player-launch]").click()
    page.locator("[data-movie-player][data-playback-state]").wait_for()
    assert captured == {
        "source_id": captured["source_id"],
        "season": 1,
        "episode": 2,
        "episodeTitle": "46 Long",
    }
    page.wait_for_function(
        "() => document.querySelector('[data-subtitle-status]')?.textContent"
        ".includes('Arabic · Season 1 Arabic is selected')"
    )
    assert any("season=1" in url and "episode=2" in url for url in subtitle_queries)
    page.locator("[data-player-selected-episode]").wait_for()
    page.screenshot(path=str(evidence_dir / "AD-episode-player-playing.png"), full_page=True)
    page.screenshot(path=str(evidence_dir / "L-episode-player-1600.png"), full_page=False)
    page.screenshot(path=str(closure_dir / "N-episode-player-sources.png"), full_page=False)
    page.locator(".tv-episode-grid").screenshot(path=str(closure_dir / "O-episode-browser.png"))
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )
    page.screenshot(path=str(evidence_dir / "AI-episode-mobile.png"), full_page=True)
    page.screenshot(path=str(unified_dir / "P-local-series-mobile-390.png"), full_page=False)
    assert not page_errors, page_errors


def test_episode_selector_stays_available_after_switching_from_season_pack(page, live_app, app):
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
        db.session.flush()
        db.session.add_all(
            [
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
                ),
                PlaybackSource(
                    movie_id=movie.id,
                    kind="magnet",
                    label="FHD magnet",
                    locator="magnet:?xt=urn:btih:89abcdef012345670123456789abcdef01234567",
                    season=1,
                    episode=1,
                    source_role="exact_episode",
                ),
            ]
        )
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MAGNETS_ENABLED=True,
        DRAGON_VIDSRC_ENABLED=False,
        DRAGON_CINESRC_ENABLED=True,
        DRAGON_SUBTITLES_ENABLED=True,
        DRAGON_SUBDL_API_KEY="private-key",
    )

    provider_requests = []

    def handle_cinesrc(route):
        provider_requests.append(route.request.url)
        route.fulfill(
            json={
                "ok": True,
                "source": {
                    "provider": "cinesrc",
                    "label": "CineSrc",
                    "url": "https://cinesrc.st/embed/tv/1399?s=1&e=1",
                    "match": "tmdb",
                },
            }
        )

    page.route("**/playback/movie/*/providers/cinesrc**", handle_cinesrc)
    page.route(
        "**/movies/api/tv/1399/seasons/1/episodes",
        lambda route: route.fulfill(
            json={
                "ok": True,
                "items": [
                    {"episode_number": 1, "name": "Pilot", "runtime_minutes": 60},
                ],
            }
        ),
    )

    sign_in(page, live_app)
    page.goto(f"{live_app}/movies/{movie_id}/seasons/1/episodes/1")
    page.wait_for_function(
        "() => document.querySelector('[data-player-pack-episode]')?.options.length > 1"
    )
    page.get_by_label("Player source").select_option(label="Local · FHD")
    page.wait_for_timeout(400)
    assert page.locator("[data-player-pack-browser]").is_visible()
    assert page.locator("[data-player-pack-episode]").input_value() == "1"
    assert page.locator("[data-subtitle-status]").is_visible()

    page.get_by_label("Player source").select_option("provider-cinesrc")
    page.wait_for_function(
        "() => document.querySelector('[data-player-source]')?.value === 'provider-cinesrc'"
    )
    assert page.locator("[data-player-pack-browser]").is_visible()
    assert page.locator("[data-player-pack-episode]").input_value() == "1"
    page.get_by_role("button", name="Play with CineSrc").click()
    page.locator("[data-player-frame]").wait_for(state="visible")
    assert page.get_by_label("Player source").is_visible()
    assert page.locator("[data-player-pack-browser]").is_visible()
    assert provider_requests and "season=1" in provider_requests[0] and "episode=1" in provider_requests[0]


def test_switching_pack_episode_stops_current_local_session_before_restart(page, live_app, app):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            media_type="tv",
            external_ids={"tmdb_id": "1399", "tmdb_type": "tv"},
            metadata_state={
                "tv_total_seasons": 1,
                "tv_total_episodes": 3,
                "tv_seasons": [
                    {"season_number": 1, "name": "Season 1", "episode_count": 3, "poster_url": ""}
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
                        {
                            "season_number": 1,
                            "episode_number": 3,
                            "name": "Denial, Anger, Acceptance",
                            "overview": "",
                            "still_url": "",
                            "runtime_minutes": 60,
                        },
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
                episode=2,
                source_role="season_pack_fallback",
                metadata_json={
                    "season_pack": True,
                    "season": 1,
                    "episode": 2,
                    "release_mode": "season_pack",
                },
                selected=True,
            )
        )
        db.session.commit()
        movie_id = movie.id

    app.config.update(
        DRAGON_PLAYBACK_ENABLED=True,
        DRAGON_MAGNETS_ENABLED=True,
        DRAGON_VIDSRC_ENABLED=False,
        DRAGON_SUBTITLES_ENABLED=False,
    )
    local_requests = []
    stop_calls = []
    page.route(
        "**/movies/api/tv/1399/seasons/1/episodes",
        lambda route: route.fulfill(
            json={
                "ok": True,
                "items": [
                    {"episode_number": 1, "name": "Pilot", "runtime_minutes": 60},
                    {"episode_number": 2, "name": "46 Long", "runtime_minutes": 60},
                    {
                        "episode_number": 3,
                        "name": "Denial, Anger, Acceptance",
                        "runtime_minutes": 60,
                    },
                ],
            }
        ),
    )

    def handle_local(route):
        local_requests.append(route.request.post_data_json)
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

    def handle_stop(route):
        stop_calls.append(route.request.url)
        route.fulfill(json={"ok": True})

    page.route("**/playback/runtime/play_pack/stop", handle_stop)

    sign_in(page, live_app)
    page.goto(f"{live_app}/movies/{movie_id}/seasons/1/episodes/2#episode-player")
    page.wait_for_function(
        "() => document.querySelector('[data-player-pack-episode]')?.options.length > 2"
    )
    page.locator("[data-player-launch]").click()
    page.locator("[data-movie-player][data-playback-state]").wait_for()
    assert local_requests[0] == {
        "source_id": local_requests[0]["source_id"],
        "season": 1,
        "episode": 2,
        "episodeTitle": "46 Long",
    }

    page.locator("[data-player-pack-episode]").select_option("3")
    page.wait_for_function(
        "() => document.querySelector('#movie-player-title')?.textContent"
        ".includes('Watch S01E03 · Denial, Anger, Acceptance')"
    )
    page.wait_for_function(
        "() => document.querySelector('[data-player-selected-episode]')?.textContent"
        ".includes('Player episode selected: S1E03')"
    )
    page.wait_for_function("() => !document.querySelector('[data-player-launch]')?.hidden")
    assert page.locator("[data-player-video]").is_hidden()
    assert stop_calls
    page.locator("[data-player-launch]").click()
    page.wait_for_timeout(200)
    assert local_requests[1] == {
        "source_id": local_requests[1]["source_id"],
        "season": 1,
        "episode": 3,
        "episodeTitle": "Denial, Anger, Acceptance",
    }
    assert "resumeSeconds" not in local_requests[1]
