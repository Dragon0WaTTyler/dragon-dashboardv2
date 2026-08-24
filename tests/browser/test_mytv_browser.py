"""Browser coverage for the My TV section."""

from datetime import UTC, datetime, timedelta

import pytest
from playwright.sync_api import expect

from app.extensions import db
from app.mytv.models import (
    TVChannel,
    TVChannelPreference,
    TVGroup,
    TVPlaylist,
    TVProgramme,
    TVTheme,
)
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
        now = datetime.now(UTC)
        playlist = TVPlaylist(
            name="Test package",
            github_path="browser.m3u",
            source_url="https://example.test/browser.m3u",
            source_sha="seed",
            imported_sha="seed",
            size_bytes=100,
            imported=True,
            channel_count=121,
            group_count=1,
            sync_status="ready",
            enabled=True,
        )
        theme = TVTheme(
            key="news", name="News", enabled=True, channel_count=121, group_count=1
        )
        group = TVGroup(name="News", theme=theme, channel_count=1)
        playlist.groups.append(group)
        archived_theme = TVTheme(
            key="archive", name="Archive", enabled=False, channel_count=1, group_count=1
        )
        archived_group = TVGroup(
            name="Archive", theme=archived_theme, channel_count=1
        )
        playlist.groups.append(archived_group)
        db.session.add(
            TVChannel(
                playlist=playlist,
                group=group,
                external_key="browser-channel",
                preference_key="browser-preference",
                name="News One",
                tvg_id="news.one",
                stream_url="https://stream.example/news.mp4",
                stream_kind="file",
                position=1,
                last_seen_sync="seed",
            )
        )
        db.session.add(
            TVChannel(
                playlist=playlist,
                group=archived_group,
                external_key="browser-archived-channel",
                preference_key="browser-archived-preference",
                name="Archived Channel",
                stream_url="https://stream.example/archived.mp4",
                stream_kind="file",
                position=1,
                last_seen_sync="seed",
            )
        )
        db.session.add_all(
            [
                TVChannel(
                    playlist=playlist,
                    group=group,
                    external_key=f"browser-channel-{index}",
                    preference_key=f"browser-preference-{index}",
                    name=f"Channel {index:03d}",
                    stream_url=f"https://stream.example/channel-{index}.mp4",
                    stream_kind="file",
                    position=index + 1,
                    last_seen_sync="seed",
                )
                for index in range(1, 121)
            ]
        )
        db.session.add_all(
            [
                TVChannelPreference(
                    preference_key="browser-preference",
                    theme_key="news",
                    name="News One",
                    tvg_id="news.one",
                    favorite=True,
                ),
                TVChannelPreference(
                    preference_key="browser-preference-1",
                    theme_key="news",
                    name="Channel 001",
                    favorite=False,
                    last_watched_at=now,
                    watch_count=1,
                ),
                TVProgramme(
                    tvg_id="news.one",
                    title="Current News",
                    starts_at=now - timedelta(minutes=20),
                    ends_at=now + timedelta(minutes=20),
                    source="browser guide",
                    fetched_at=now,
                ),
                TVProgramme(
                    tvg_id="news.one",
                    title="Next News",
                    starts_at=now + timedelta(minutes=20),
                    ends_at=now + timedelta(hours=1),
                    source="browser guide",
                    fetched_at=now,
                ),
            ]
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
        Object.defineProperty(HTMLMediaElement.prototype, "paused", {
          configurable: true,
          get() { return this.dataset.testPaused !== "false"; },
        });
        HTMLMediaElement.prototype.load = function () {
          this.dispatchEvent(new Event("loadeddata"));
        };
        HTMLMediaElement.prototype.play = function () {
          this.dataset.testPaused = "false";
          this.dispatchEvent(new Event("playing"));
          return Promise.resolve();
        };
        HTMLMediaElement.prototype.pause = function () {
          this.dataset.testPaused = "true";
          this.dispatchEvent(new Event("pause"));
        };
        """
    )
    page.goto(f"{live_app}/iptv")
    assert page.get_by_role("heading", name="IPTV", level=1).count() == 1
    page.get_by_text("Channel 001", exact=True).wait_for()
    current_mobile_item = page.locator(
        "nav[aria-label='Mobile navigation'] a[aria-current='page']"
    )
    assert current_mobile_item.inner_text().endswith("IPTV")
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
    assert page.get_by_role("button", name="Check availability").is_hidden()
    assert page.get_by_label("Bouquet", exact=True).count() == 0
    assert page.locator("#stateFilter").input_value() == "enabled"
    assert page.get_by_role("button", name="Favorites", exact=True).is_visible()
    assert page.get_by_role("button", name="Resume Channel 001").is_visible()
    assert page.get_by_text("Live", exact=True).is_hidden()
    assert page.get_by_role("button", name="Picture in picture").is_hidden()
    playback_requests = []

    def reject_playback(route):
        playback_requests.append(route.request.url)
        route.fulfill(
            status=503,
            content_type="application/json",
            body='{"message":"Browser playback failure"}',
        )

    page.route("**/iptv/api/channels/*/playback", reject_playback)
    page.get_by_role("button", name="Play Channel 001").click()
    expect(page.locator("#playerLoadingText")).to_have_text(
        "Browser playback failure", timeout=5000
    )
    expect(page.locator("#retryPlayback")).to_be_visible()
    expect(page.locator("#playerEmpty")).to_be_hidden()
    expect(page.locator("#nowPlayingTitle")).to_have_text("Channel 001")
    assert len(playback_requests) == 1
    expect(page.get_by_role("button", name="Previous channel")).to_be_visible()
    expect(page.get_by_role("button", name="Next channel")).to_be_visible()
    expect(page.get_by_role("button", name="Previous channel")).to_be_enabled()
    expect(page.get_by_role("button", name="Next channel")).to_be_enabled()
    page.unroute("**/iptv/api/channels/*/playback")
    page.evaluate(
        """() => {
          document.querySelector('[data-channel-view="favorites"]').click();
          document.querySelector('[data-channel-view="recent"]').click();
        }"""
    )
    expect(page.get_by_role("button", name="Recent", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(page.locator("#channelGrid").get_by_text("Channel 001", exact=True)).to_be_visible(
        timeout=3000
    )
    expect(page.locator("#channelGrid .tv-channel-card")).to_have_count(1)
    expect(page.locator("#channelViewTitle")).to_have_text("Recently watched")
    expect(page.locator("#channelViewCount")).to_have_text("1 channel")
    page.get_by_role("button", name="Ready", exact=True).click()
    page.get_by_text("Channel 002", exact=True).wait_for()
    expect(page.locator("#channelViewTitle")).to_have_text("Ready to watch")
    expect(page.locator("#channelViewCount")).to_have_text("121 channels")
    expect(page.get_by_text("Archived Channel", exact=True)).to_have_count(0)

    def reject_channel_list(route):
        route.fulfill(
            status=503,
            content_type="application/json",
            body='{"message":"Channel list temporarily unavailable"}',
        )

    page.route("**/iptv/api/channels?*", reject_channel_list)
    page.get_by_role("button", name="Disabled", exact=True).click()
    expect(page.locator("#channelLoadStatus")).to_have_text(
        "Could not load channels. Retry when you are ready."
    )
    expect(page.get_by_role("button", name="Retry loading channels")).to_be_visible()
    page.unroute("**/iptv/api/channels?*", reject_channel_list)
    page.get_by_role("button", name="Retry loading channels").click()
    expect(page.locator("#channelViewTitle")).to_have_text("Disabled channels")
    expect(page.get_by_text("Archived Channel", exact=True)).to_be_visible()

    page.get_by_role("button", name="All", exact=True).click()
    expect(page.get_by_text("Archived Channel", exact=True)).to_be_visible()
    expect(page.locator("#channelViewTitle")).to_have_text("All channels")
    expect(page.locator("#channelViewCount")).to_have_text("122 channels")
    expect(page.get_by_role("button", name="Play Archived Channel")).to_be_disabled()
    page.get_by_role("button", name="Ready", exact=True).click()
    page.get_by_text("Channel 002", exact=True).wait_for()
    assert page.locator(".tv-watch-toolbar > .tv-visibility-filter").count() == 1
    assert page.locator(".tv-filters #stateFilter").count() == 0
    assert page.get_by_text("Quick control", exact=True).count() == 0
    assert page.get_by_text("All active bouquets", exact=True).count() == 0
    watch_search = page.get_by_label("Search watch channels")
    assert watch_search.is_visible()
    watch_search.fill("News One")
    page.get_by_text("News One", exact=True).wait_for()
    assert page.locator(".tv-channel-guide", has_text="Current News").is_visible()
    assert page.locator(".tv-channel-next", has_text="Next News").is_visible()
    watch_logos = page.locator("#channelGrid[role='list'] .tv-channel-logo")
    expect(watch_logos).to_have_count(1)
    search_box = page.locator(".tv-watch-search").bounding_box()
    result_box = page.locator("#channelGrid .tv-channel-card").bounding_box()
    assert search_box and result_box
    assert abs(result_box["y"] - (search_box["y"] + search_box["height"])) <= 2
    assert result_box["height"] <= 80
    target_size = page.get_by_role(
        "button", name="Remove News One from favorites"
    ).bounding_box()
    assert target_size and target_size["width"] >= 44 and target_size["height"] >= 44
    watch_search.fill("")
    page.get_by_text("Channel 001", exact=True).wait_for()
    expect(watch_logos).to_have_count(100)
    assert page.locator("#channelGrid[role='list'] .tv-channel-logo").count() == 100
    assert page.get_by_role("button", name="Load more channels").is_visible()
    assert page.get_by_label("Channel availability for News One").count() == 0
    assert page.get_by_role("button", name="Previous channel page").count() == 0
    assert page.get_by_role("button", name="Next channel page").count() == 0
    page.get_by_role("button", name="Load more channels").click()
    page.get_by_text("News One", exact=True).wait_for()
    assert page.locator("#channelGrid[role='list'] .tv-channel-logo").count() == 121
    page.get_by_role("button", name="Play Channel 001").focus()
    page.keyboard.press("ArrowDown")
    expect(page.get_by_role("button", name="Play Channel 002")).to_be_focused()
    card_copy = page.locator(".tv-channel-card .tv-channel-copy", has_text="News One")
    assert "News One" in card_copy.inner_text()
    page.get_by_role("button", name="Play News One").click()
    page.locator("#playerLoading").wait_for(state="hidden")
    assert page.get_by_text("Live", exact=True).is_visible()
    active_src = page.locator("#videoPlayer").get_attribute("data-test-src")
    expect(page.get_by_label("Live player controls")).to_be_visible()
    expect(page.locator("#playerOverlayTitle")).to_have_attribute("data-channel-name", "News One")
    expect(page.get_by_role("button", name="Previous channel")).to_be_visible()
    expect(page.get_by_role("button", name="Next channel")).to_be_visible()
    expect(page.get_by_role("button", name="Pause live channel")).to_be_visible()
    expect(page.locator("#playerConnectionState")).to_have_text("Live now")
    page.get_by_role("button", name="Pause live channel").click()
    expect(page.locator("#playerConnectionState")).to_have_text("Live channel paused")
    page.get_by_role("button", name="Play live channel").click()
    expect(page.locator("#playerConnectionState")).to_have_text("Live now")
    page.locator("#playerFrame").evaluate(
        "element => element.dispatchEvent(new WheelEvent('wheel', "
        "{ bubbles: true, cancelable: true, deltaY: 100 }))"
    )
    assert page.locator("#videoPlayer").evaluate("element => element.volume") < 1
    expect(page.locator("#playerVolumeFeedback")).to_have_class(
        "tv-player-volume-feedback is-visible"
    )
    expect(page.locator("#playerVolumeValue")).to_have_text("95%")
    page.locator("#playerFrame").dispatch_event("pointerleave")
    expect(page.get_by_label("Live player controls")).to_be_hidden()
    expect(page.locator("#playerOverlayTitle")).to_be_hidden()
    page.locator("#playerFrame").dispatch_event("pointermove")
    expect(page.get_by_label("Live player controls")).to_be_visible()
    expect(page.locator("#playerOverlayTitle")).to_be_visible()
    page.locator("#fullscreenPlayer").focus()
    page.wait_for_timeout(2600)
    expect(page.get_by_label("Live player controls")).to_be_hidden()
    expect(page.locator("#playerOverlayTitle")).to_be_hidden()
    page.locator("#playerFrame").dispatch_event("pointermove")
    page.get_by_role("button", name="Enter theater mode").click()
    assert "is-theater" in (page.locator("#tv-panel-watch").get_attribute("class") or "")
    page.get_by_role("button", name="Exit theater mode").click()
    assert "is-theater" not in (page.locator("#tv-panel-watch").get_attribute("class") or "")
    page.get_by_role("button", name="Recent", exact=True).click()
    page.get_by_text("Channel 001", exact=True).wait_for()
    assert page.locator("#videoPlayer").is_visible()
    assert page.locator("#videoPlayer").get_attribute("data-test-src") == active_src
    assert page.get_by_text("Live", exact=True).is_visible()
    page.get_by_role("button", name="Ready", exact=True).click()
    page.get_by_text("Channel 002", exact=True).wait_for()
    assert page.locator("#playerShell").evaluate(
        "element => getComputedStyle(element.querySelector('.tv-player-frame')).position"
    ) == "sticky"
    page.keyboard.press("m")
    assert page.locator("#videoPlayer").evaluate("element => element.muted") is True
    page.keyboard.press("/")
    assert watch_search.evaluate("element => document.activeElement === element") is True

    page.set_viewport_size({"width": 1440, "height": 900})
    quick_control_box = page.locator(".tv-filters").bounding_box()
    player_box = page.locator(".tv-player-shell").bounding_box()
    watch_layout_box = page.locator(".tv-watch-layout").bounding_box()
    assert quick_control_box and player_box
    assert watch_layout_box
    assert watch_layout_box["height"] <= 652
    assert page.locator("#channelGrid").evaluate(
        "element => element.scrollHeight > element.clientHeight"
    ) is True
    page.get_by_role("button", name="All", exact=True).click()
    expect(page.get_by_text("Archived Channel", exact=True)).to_be_visible()
    all_layout_box = page.locator(".tv-watch-layout").bounding_box()
    assert all_layout_box and all_layout_box["height"] <= 652
    assert page.locator("#channelGrid").evaluate(
        "element => element.scrollHeight > element.clientHeight"
    ) is True
    assert player_box["x"] < quick_control_box["x"]
    assert abs(player_box["height"] - quick_control_box["height"]) <= 2
    assert page.locator("#channelEmpty").is_hidden()
    rtl = page.evaluate(
        """() => {
          document.documentElement.dir = "rtl";
          const player = document.querySelector(".tv-player-shell").getBoundingClientRect();
          const channels = document.querySelector(".tv-filters").getBoundingClientRect();
          return {
            overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
            playerRightOfChannels: player.x > channels.x,
          };
        }"""
    )
    assert rtl == {"overflow": 0, "playerRightOfChannels": True}
    page.evaluate('document.documentElement.dir = "ltr"')

    page.get_by_role("tab", name="Manage", exact=True).click()
    assert page.locator("#videoPlayer").evaluate("element => element.paused") is False
    assert page.get_by_role("heading", name="Keep channels current", level=2).is_visible()
    assert page.get_by_role("heading", name="Channel exceptions", level=2).is_visible()
    assert page.get_by_role("button", name="Check availability").is_visible()
    assert page.locator("[data-toggle-source]").count() == 0
    assert page.get_by_role("switch", name="Deactivate group News").is_visible()
    bouquet_view = page.get_by_label("Show groups")
    assert bouquet_view.input_value() == "all"
    bouquet_view.select_option("on")
    assert page.get_by_role("switch", name="Deactivate group News").is_visible()
    bouquet_view.select_option("off")
    page.get_by_role("switch", name="Activate group Archive").wait_for()
    bouquet_view.select_option("all")
    page.get_by_role("switch", name="Deactivate group News").click()
    assert page.get_by_text("Deactivate News?", exact=True).is_visible()
    page.get_by_role("button", name="Cancel").click()
    news_bouquet = page.locator(".tv-bouquet-row", has_text="News")
    news_bouquet.get_by_role("button", name="Turn all off").click()
    assert page.get_by_text("Turn off 121 channels?", exact=True).is_visible()
    news_bouquet.get_by_role("button", name="Turn all off", exact=True).last.click()
    undo = page.get_by_role("button", name="Undo")
    undo.wait_for()
    undo.click()
    expect(news_bouquet.get_by_role("button", name="Turn all off").first).to_be_focused()
    page.get_by_label("Search channels").fill("News One")
    availability = page.get_by_label("Channel availability for News One")
    availability.wait_for()
    assert availability.input_value() == "default"
    availability.select_option("off")
    expect(availability).to_be_focused()
    assert availability.input_value() == "off"

    page.get_by_role("tab", name="Watch", exact=True).click()
    page.locator("#channelGrid").get_by_text("Channel 001", exact=True).wait_for()
    first = page.get_by_role("button", name="Play Channel 001")
    second = page.get_by_role("button", name="Play Channel 002")
    first_id = first.get_attribute("data-play-channel")
    second_id = second.get_attribute("data-play-channel")
    page.evaluate(
        """firstId => {
          const nativeFetch = window.fetch.bind(window);
          window.fetch = (url, options = {}) => {
            if (!String(url).endsWith(`/channels/${firstId}/playback`)) {
              return nativeFetch(url, options);
            }
            return new Promise((resolve, reject) => {
              const timer = window.setTimeout(
                () => nativeFetch(url, options).then(resolve, reject),
                300,
              );
              options.signal?.addEventListener("abort", () => {
                window.clearTimeout(timer);
                reject(new DOMException("Playback request replaced", "AbortError"));
              }, { once: true });
            });
          };
        }""",
        first_id,
    )
    first.click()
    second.click()
    expect(page.locator("#nowPlayingTitle")).to_have_text("Channel 002")
    page.wait_for_timeout(450)
    expect(page.locator("#nowPlayingTitle")).to_have_text("Channel 002")
    assert page.locator("#videoPlayer").get_attribute("data-test-src") == f"/iptv/play/{second_id}"
