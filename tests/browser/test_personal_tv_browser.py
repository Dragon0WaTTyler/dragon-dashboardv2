from datetime import UTC, datetime

import pytest
from playwright.sync_api import expect

from app.extensions import db
from app.youtube.models import YouTubeVideo

pytestmark = pytest.mark.browser


def sign_in(page, base_url: str):
    page.goto(f"{base_url}/auth/login")
    page.get_by_label("Username").fill("walid")
    page.get_by_label("Password").fill("correct horse battery staple")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"{base_url}/")


def test_personal_tv_builds_a_session_from_youtube_groups(page, live_app, app):
    with app.app_context():
        db.session.add_all(
            [
                YouTubeVideo(
                    external_id="science-one",
                    source="pockettube",
                    group_name="Science & Knowledge",
                    channel_title="Source One",
                    title="Science programme one",
                    duration_seconds=1800,
                    published_at=datetime(2026, 8, 20, tzinfo=UTC),
                ),
                YouTubeVideo(
                    external_id="science-two",
                    source="pockettube",
                    group_name="Science & Knowledge",
                    channel_title="Source Two",
                    title="Science programme two",
                    duration_seconds=1500,
                    published_at=datetime(2026, 8, 20, tzinfo=UTC),
                ),
                YouTubeVideo(
                    external_id="science-one::pt:favo",
                    source="pockettube",
                    group_name="my favoret",
                    channel_title="Source One",
                    title="Science programme one",
                    duration_seconds=1800,
                    published_at=datetime(2026, 8, 20, tzinfo=UTC),
                ),
                YouTubeVideo(
                    external_id="archive-one::pt:review",
                    source="pockettube",
                    group_name="Archive / Review Later",
                    channel_title="Archived source",
                    title="Archived programme",
                    duration_seconds=1800,
                    published_at=datetime(2026, 8, 20, tzinfo=UTC),
                ),
            ]
        )
        db.session.commit()

    page.set_viewport_size({"width": 390, "height": 844})
    sign_in(page, live_app)
    page.goto(f"{live_app}/my-tv")
    expect(page.get_by_role("heading", name="My TV", level=1)).to_be_visible()
    expect(page.get_by_text("My TV collections")).to_be_visible()
    expect(page.get_by_role("button", name="my favoret1")).to_be_visible()
    expect(page.get_by_text("Archive / Review Later")).not_to_be_visible()
    expect(page.get_by_role("button", name="90m")).to_be_visible()
    page.get_by_role("button", name="90m").click()
    page.get_by_role("button", name="Science & Knowledge2").click()
    page.get_by_role("button", name="Start My TV").click()
    expect(page.get_by_text("My TV · active session")).to_be_visible()
    expect(page.get_by_role("heading", name="Science programme one")).to_be_visible()
    page.get_by_role("button", name="Skip").click()
    expect(page.get_by_role("heading", name="Science programme two")).to_be_visible()
