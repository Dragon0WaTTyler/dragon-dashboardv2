"""Browser coverage for the My TV section."""

import pytest

from app.extensions import db
from app.mytv.models import TVChannel, TVGroup, TVPlaylist, TVTheme
from app.mytv.services import GithubTVSync

pytestmark = pytest.mark.browser


def sign_in(page, base_url: str):
    page.goto(f"{base_url}/auth/login")
    page.get_by_label("Username").fill("walid")
    page.get_by_label("Password").fill("correct horse battery staple")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"{base_url}/")


def test_mytv_is_integrated_responsive_and_manageable(page, live_app, app):
    with app.app_context():
        playlist = TVPlaylist(
            name="Test package",
            github_path="browser.m3u",
            source_url="https://example.test/browser.m3u",
            source_sha="seed",
            imported_sha="seed",
            size_bytes=100,
            imported=True,
            channel_count=1,
            group_count=1,
            sync_status="ready",
            enabled=True,
        )
        theme = TVTheme(
            key="news", name="News", enabled=True, channel_count=1, group_count=1
        )
        group = TVGroup(name="News", theme=theme, channel_count=1)
        playlist.groups.append(group)
        db.session.add(
            TVChannel(
                playlist=playlist,
                group=group,
                external_key="browser-channel",
                preference_key="browser-preference",
                name="News One",
                stream_url="https://stream.example/news.mp4",
                stream_kind="file",
                position=1,
                last_seen_sync="seed",
            )
        )
        db.session.commit()
        GithubTVSync.refresh_representatives()

    page.set_viewport_size({"width": 390, "height": 844})
    sign_in(page, live_app)
    page.add_init_script(
        """
        Object.defineProperty(HTMLMediaElement.prototype, "src", {
          configurable: true,
          get() { return this.dataset.testSrc || ""; },
          set(value) { this.dataset.testSrc = value; },
        });
        HTMLMediaElement.prototype.load = function () {
          this.dispatchEvent(new Event("loadeddata"));
        };
        HTMLMediaElement.prototype.play = function () { return Promise.resolve(); };
        HTMLMediaElement.prototype.pause = function () {};
        """
    )
    page.goto(f"{live_app}/my-tv")
    assert page.get_by_role("heading", name="My TV", level=1).count() == 1
    page.get_by_text("News One", exact=True).wait_for()
    current_mobile_item = page.locator(
        "nav[aria-label='Mobile navigation'] a[aria-current='page']"
    )
    assert current_mobile_item.inner_text().endswith("My TV")
    metrics = page.evaluate(
        """() => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
          unlabeled: [...document.querySelectorAll('input:not([type=hidden]), select')]
            .filter((element) => !element.closest('label') && !element.getAttribute('aria-label'))
            .length,
        })"""
    )
    assert metrics["scrollWidth"] == metrics["clientWidth"]
    assert metrics["unlabeled"] == 0
    assert page.get_by_role("button", name="Check channels").is_visible()
    page.get_by_role("button", name="Play News One").click()
    page.locator("#playerLoading").wait_for(state="hidden")

    page.get_by_role("button", name="Manage", exact=True).click()
    assert page.get_by_role("heading", name="GitHub catalogue", level=2).is_visible()
    assert page.locator("[data-toggle-source]").count() == 0
    assert page.get_by_role("switch", name="Disable bouquet News").is_visible()
    bouquet_view = page.get_by_label("Show bouquets")
    assert bouquet_view.input_value() == "all"
    bouquet_view.select_option("on")
    assert page.get_by_role("switch", name="Disable bouquet News").is_visible()
    bouquet_view.select_option("off")
    page.get_by_role("heading", name="No bouquets are off", level=3).wait_for()
