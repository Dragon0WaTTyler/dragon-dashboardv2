import re

import pytest

from app.books.models import Book
from app.extensions import db
from app.movies.models import Movie
from app.reading.models import Article, ReadingSource
from app.youtube.models import YouTubeVideo

pytestmark = pytest.mark.browser


def sign_in(page, base_url: str):
    page.goto(f"{base_url}/auth/login")
    page.get_by_label("Username").fill("walid")
    page.get_by_label("Password").fill("correct horse battery staple")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"{base_url}/")


def test_desktop_shell_keyboard_and_dialog(page, live_app):
    page.set_viewport_size({"width": 1440, "height": 900})
    sign_in(page, live_app)
    assert page.get_by_role("heading", name="Today", level=1).count() == 1
    assert page.locator("main").count() == 1
    assert page.locator("nav[aria-label='Primary navigation']").count() == 1

    trigger = page.get_by_role("button", name=re.compile("Search or open"))
    trigger.focus()
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog", name="Where do you want to go?")
    assert dialog.is_visible()
    page.keyboard.press("Escape")
    assert not dialog.is_visible()
    assert trigger.evaluate("element => element === document.activeElement")


def test_mobile_shell_has_no_overflow_and_safe_targets(page, live_app):
    page.set_viewport_size({"width": 390, "height": 844})
    sign_in(page, live_app)
    metrics = page.evaluate(
        """() => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
          appBarTops: [
            document.querySelector('.brand'),
            document.querySelector('.command-trigger'),
            document.querySelector('.account-menu'),
          ].map((element) => Math.round(element.getBoundingClientRect().top)),
          smallTargets: [...document.querySelectorAll('a[href], button, input, select')]
            .filter((element) => {
              const rect = element.getBoundingClientRect();
              return rect.width > 0 && rect.height > 0 && (rect.width < 44 || rect.height < 44);
            })
            .map((element) => element.textContent.trim()).slice(0, 10),
        })"""
    )
    assert metrics["scrollWidth"] == metrics["clientWidth"]
    assert max(metrics["appBarTops"]) - min(metrics["appBarTops"]) <= 2
    assert metrics["smallTargets"] == []
    assert page.locator("nav[aria-label='Mobile navigation']").is_visible()


def test_login_and_design_system_semantics(page, live_app):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{live_app}/auth/login")
    assert page.get_by_role("heading", name="Enter the archive.", level=1).count() == 1
    assert page.get_by_label("Username").count() == 1
    assert page.get_by_label("Password").count() == 1
    sign_in(page, live_app)
    page.goto(f"{live_app}/admin/design-system")
    assert page.get_by_role("heading", name="Design system", level=1).count() == 1
    assert page.locator("[style]").count() == 0


def test_library_grid_thumbnails_and_rtl_direction(page, live_app, app):
    image = (
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
        "width='40' height='60'%3E%3Crect width='40' height='60' fill='%23b51f32'/%3E%3C/svg%3E"
    )
    with app.app_context():
        source = ReadingSource(name="مجلة", feed_url="https://example.test/feed")
        db.session.add_all(
            [
                Book(
                    title="كتاب عربي",
                    normalized_title="كتاب عربي",
                    authors=["كاتب"],
                    cover_url=image,
                    status="reading",
                ),
                Article(
                    source=source,
                    title="مقال عربي",
                    url="https://example.test/article",
                    image_url=image,
                ),
                Movie(
                    title="Daily Movie",
                    normalized_title="daily movie",
                    status="want_to_watch",
                    poster_url=image,
                ),
                YouTubeVideo(
                    external_id="home-video",
                    source="watch_later",
                    channel_title="Home Channel",
                    title="Home video",
                    thumbnail_url=image,
                ),
            ]
        )
        db.session.commit()

    sign_in(page, live_app)
    page.goto(f"{live_app}/books")
    display = page.locator(".book-grid").evaluate(
        "element => getComputedStyle(element).display"
    )
    assert display == "grid"
    column_count = page.locator(".book-grid").evaluate(
        "element => getComputedStyle(element).gridTemplateColumns.split(' ').length"
    )
    assert column_count == 5
    assert page.locator(".book-cover img").is_visible()
    book_card_metrics = page.locator(".book-card").first.evaluate(
        "element => ({"
        "cardWidth: element.getBoundingClientRect().width,"
        "badgeWidth: element.querySelector('.badge').getBoundingClientRect().width"
        "})"
    )
    assert book_card_metrics["badgeWidth"] < book_card_metrics["cardWidth"]
    assert page.locator(".book-card h2").evaluate(
        "element => getComputedStyle(element).direction"
    ) == "rtl"

    page.set_viewport_size({"width": 390, "height": 844})
    mobile_column_count = page.locator(".book-grid").evaluate(
        "element => getComputedStyle(element).gridTemplateColumns.split(' ').length"
    )
    assert mobile_column_count == 2
    page.set_viewport_size({"width": 1280, "height": 720})

    page.goto(f"{live_app}/reading")
    assert page.locator(".article-card__image img").is_visible()
    assert page.locator(".article-card h2").evaluate(
        "element => getComputedStyle(element).direction"
    ) == "rtl"

    page.route(
        "**/api/v1/home/live",
        lambda route: route.fulfill(
            json={
                "ok": True,
                "api_version": "v1",
                "item": {
                    "recommended_movie": {
                        "id": "rotated-movie",
                        "title": "Rotated Movie",
                        "year": 2026,
                        "personal_score": 5,
                        "poster_url": image,
                    },
                    "latest_youtube": [
                        {
                            "id": "rotated-video",
                            "title": "Rotated video",
                            "channel_title": "Rotated Channel",
                            "thumbnail_url": image,
                        }
                    ],
                    "rotation": {
                        "movie_bucket": 999999,
                        "youtube_bucket": 999999,
                        "movie_interval_seconds": 3600,
                        "youtube_interval_seconds": 300,
                        "movie_next_at": "2099-01-01T01:00:00Z",
                        "youtube_next_at": "2099-01-01T00:05:00Z",
                    },
                },
            }
        ),
    )
    page.goto(f"{live_app}/")
    assert page.locator(".today-feature__poster img").is_visible()
    assert page.locator(".today-media-card__image img").is_visible()
    assert page.locator(".today-article-feature__image img").is_visible()
    assert page.locator(".today-book__cover img").is_visible()
    page.locator("[data-today-live]").dispatch_event("today:refresh")
    page.get_by_text("Rotated Movie", exact=True).wait_for()
    assert page.locator("[data-live-youtube-title]").first.inner_text() == "Rotated video"


def test_movie_recommendation_and_more_filters_stay_in_flow(page, live_app, app):
    with app.app_context():
        db.session.add_all(
            [
                Movie(
                    title="In the Mood for Love",
                    normalized_title="in the mood for love",
                    status="finished",
                    personal_score=8,
                    category="movie",
                    source="My library",
                    directors=[{"name": "Wong Kar-wai"}],
                    genres=[{"name": "Drama"}],
                ),
                Movie(
                    title="Chungking Express",
                    normalized_title="chungking express",
                    year=1994,
                    runtime_minutes=102,
                    status="want_to_watch",
                    category="movie",
                    source="My library",
                    overview="Two stories of love and chance in Hong Kong.",
                    poster_url="https://example.test/chungking.jpg",
                    directors=[{"name": "Wong Kar-wai"}],
                    genres=[{"name": "Drama"}],
                ),
                Movie(
                    title="Happy Together",
                    normalized_title="happy together",
                    year=1997,
                    runtime_minutes=96,
                    status="want_to_watch",
                    category="movie",
                    source="My library",
                    overview="A relationship shifts during a journey to Argentina.",
                    poster_url="https://example.test/happy-together.jpg",
                    directors=[{"name": "Wong Kar-wai"}],
                    genres=[{"name": "Drama"}],
                ),
            ]
        )
        db.session.commit()

    page.set_viewport_size({"width": 1440, "height": 900})
    sign_in(page, live_app)
    page.goto(f"{live_app}/movies")
    option_colors = page.locator("select[name='status'] option").first.evaluate(
        """element => ({
          background: getComputedStyle(element).backgroundColor,
          color: getComputedStyle(element).color,
        })"""
    )
    assert option_colors == {
        "background": "rgb(23, 19, 19)",
        "color": "rgb(244, 240, 233)",
    }
    page.locator(".filter-more summary").click()
    layout = page.evaluate(
        """() => {
          const panel = document.querySelector('.filter-more__panel');
          const results = document.querySelector('.movie-grid');
          return {
            position: getComputedStyle(panel).position,
            panelBottom: panel.getBoundingClientRect().bottom,
            resultsTop: results.getBoundingClientRect().top,
          };
        }"""
    )
    assert layout["position"] == "static"
    assert layout["panelBottom"] <= layout["resultsTop"]

    page.get_by_role("button", name="What should I watch?").click()
    recommendation = page.locator("[data-recommendation-card]")
    recommendation.wait_for(state="visible")
    first_title = recommendation.locator("h2").inner_text()
    page.get_by_role("button", name="Try another").click()
    assert recommendation.locator("h2").inner_text() != first_title


@pytest.mark.parametrize(
    ("path", "heading"),
    [
        ("/", "Today"),
        ("/movies", "Movies"),
        ("/youtube", "YouTube"),
        ("/reading", "Reading"),
        ("/books", "Books"),
        ("/chess", "Chess"),
        ("/german", "German"),
        ("/history", "History"),
        ("/admin", "Admin"),
        ("/ai/workspace", "Movie Curation"),
    ],
)
def test_primary_pages_mobile_accessibility_and_overflow(page, live_app, path, heading):
    page.set_viewport_size({"width": 390, "height": 844})
    sign_in(page, live_app)
    page.goto(f"{live_app}{path}")
    assert page.get_by_role("heading", name=heading, level=1).count() == 1
    assert page.locator("main").count() == 1
    assert page.locator("[style]").count() == 0
    metrics = page.evaluate(
        """() => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
          unlabeled: [...document.querySelectorAll('input:not([type=hidden]), select, textarea')]
            .filter((element) => !element.closest('label') && !element.getAttribute('aria-label'))
            .length,
        })"""
    )
    assert metrics["scrollWidth"] == metrics["clientWidth"]
    assert metrics["unlabeled"] == 0
