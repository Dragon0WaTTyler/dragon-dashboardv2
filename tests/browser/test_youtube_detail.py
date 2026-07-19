import pytest

from app.extensions import db
from app.youtube.models import YouTubeVideo

pytestmark = pytest.mark.browser


def sign_in(page, base_url: str):
    page.goto(f"{base_url}/auth/login")
    page.get_by_label("Username").fill("walid")
    page.get_by_label("Password").fill("correct horse battery staple")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"{base_url}/")


def test_youtube_detail_loads_large_player_only_after_click(page, live_app, app):
    image = (
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
        "width='1280' height='720'%3E%3Crect width='1280' height='720' "
        "fill='%23211919'/%3E%3C/svg%3E"
    )
    with app.app_context():
        video = YouTubeVideo(
            external_id="browser-video",
            source="watch_later",
            channel_title="قناة هادئة",
            title="شرح عربي منظم",
            description="هذا وصف عربي للفيديو.\n\n00:00 المقدمة\n01:25 الفكرة الرئيسية",
            thumbnail_url=image,
            duration_seconds=600,
        )
        db.session.add(video)
        db.session.commit()
        video_id = video.id

    embed_requests = []

    def fulfill_embed(route):
        embed_requests.append(route.request.url)
        route.fulfill(
            content_type="text/html",
            body="<main><h1>Embedded YouTube player</h1></main>",
        )

    page.route("https://www.youtube-nocookie.com/**", fulfill_embed)
    page.route(
        "https://www.youtube.com/iframe_api",
        lambda route: route.fulfill(
            content_type="application/javascript",
            body=(
                "window.YT={PlayerState:{PLAYING:1,PAUSED:2,ENDED:0},"
                "Player:function(frame, config){this.getCurrentTime=function(){return 0};"
                "this.getDuration=function(){return 600};this.seekTo=function(){};"
                "this.playVideo=function(){};config.events.onReady({target:this});}};"
                "window.onYouTubeIframeAPIReady();"
            ),
        ),
    )

    page.set_viewport_size({"width": 1440, "height": 900})
    sign_in(page, live_app)
    page.goto(f"{live_app}/youtube/{video_id}")
    assert embed_requests == []
    assert page.get_by_role("heading", name="شرح عربي منظم", level=1).count() == 1
    assert page.locator(".youtube-detail__header h1").evaluate(
        "element => getComputedStyle(element).direction"
    ) == "rtl"
    player = page.locator("[data-youtube-player]")
    focus_button = page.locator("[data-player-focus]")
    assert focus_button.is_visible()
    assert focus_button.evaluate(
        "button => button.getBoundingClientRect().bottom"
    ) <= player.evaluate("element => element.getBoundingClientRect().top")
    ratio = player.evaluate(
        "element => element.getBoundingClientRect().width / element.getBoundingClientRect().height"
    )
    assert 1.75 < ratio < 1.8

    page.get_by_role("button", name="Play شرح عربي منظم here").click()
    page.frame_locator("[data-player-frame]").get_by_role(
        "heading", name="Embedded YouTube player"
    ).wait_for()
    assert embed_requests
    assert page.locator("[data-player-frame]").is_visible()
    assert not page.locator("[data-player-launch]").is_visible()
    assert not page.get_by_text("Play here", exact=True).is_visible()
    assert page.locator("[data-player-toolbar]").count() == 0
    assert focus_button.is_visible()

    focus_button.click()
    assert page.locator("[data-youtube-detail].is-focus-mode").count() == 1
    assert page.locator(".youtube-detail__header").evaluate(
        "element => getComputedStyle(element).display"
    ) == "none"
    assert focus_button.text_content() == "Exit focus mode"

    page.keyboard.press("Escape")
    assert page.locator("[data-youtube-detail].is-focus-mode").count() == 0
    assert focus_button.text_content() == "Enter focus mode"

    title_alignment = page.locator(".youtube-detail__header").evaluate(
        """header => {
          const title = header.querySelector('h1');
          const headerBox = header.getBoundingClientRect();
          const titleBox = title.getBoundingClientRect();
          return Math.abs(headerBox.right - titleBox.right);
        }"""
    )
    assert title_alignment < 2

    page.set_viewport_size({"width": 390, "height": 844})
    metrics = page.evaluate(
        """() => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
        })"""
    )
    assert metrics["scrollWidth"] == metrics["clientWidth"]
