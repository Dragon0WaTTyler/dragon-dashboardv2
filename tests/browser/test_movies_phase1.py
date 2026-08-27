from __future__ import annotations

from pathlib import Path

import pytest

from app.extensions import db
from app.movies.models import Movie, MovieProgress

pytestmark = pytest.mark.browser


def _art(label: str, start: str, end: str) -> str:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="960">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop stop-color="{start}"/><stop offset="1" stop-color="{end}"/></linearGradient></defs>'
        f'<rect width="100%" height="100%" fill="url(#g)"/><text x="48" y="820" '
        f'fill="white" font-size="42" font-family="sans-serif">{label}</text></svg>'
    )
    return "data:image/svg+xml," + svg.replace("#", "%23").replace(" ", "%20")


def _sign_in(page, base_url: str):
    page.goto(f"{base_url}/auth/login")
    page.get_by_label("Username").fill("walid")
    page.get_by_label("Password").fill("correct horse battery staple")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"{base_url}/")


class Phase1Provider:
    configured = True

    def provider_catalog(self, media_type, *, region):
        return [
            {"id": 8, "name": "Netflix", "logo_url": _art("NETFLIX", "#321", "#e50914")},
            {"id": 9, "name": "Prime Video", "logo_url": _art("PRIME", "#123", "#23a6d5")},
            {"id": 337, "name": "Disney Plus", "logo_url": _art("DISNEY+", "#102b55", "#2255a4")},
        ]

    def discover(self, media_type, **kwargs):
        provider_id = kwargs.get("provider_id")
        prefix = "Movie" if media_type == "movie" else "Series"
        return {
            "items": [
                {
                    "tmdb_id": (800 if media_type == "movie" else 900) + index,
                    "media_type": media_type,
                    "title": f"{prefix} on provider {provider_id} {index}",
                    "poster_url": _art(prefix, "#251b3d", "#d32f5f"),
                    "year": 2025 - index,
                    "rating": 7.8 - (index / 10),
                }
                for index in range(1, 7)
            ],
            "page": 1,
            "total_pages": 1,
        }

    def trending(self, media_type, *, limit):
        return self.discover(media_type, provider_id=8, region="US", sort="popular", page=1)[
            "items"
        ]

    def catalog(self, media_type, kind, *, limit):
        return self.discover(media_type, provider_id=8, region="US", sort="popular", page=1)[
            "items"
        ]

    def details(self, media_type, tmdb_id):
        return {
            "tmdb_id": tmdb_id,
            "media_type": media_type,
            "type_label": "Movie" if media_type == "movie" else "Series",
            "title": "Preview Candidate",
            "year": 2024,
            "overview": "A TMDB-only title used to verify stateless preview presentation.",
            "poster_url": _art("PREVIEW", "#1b2840", "#8b4a75"),
            "backdrop_url": _art("PREVIEW", "#1b2840", "#8b4a75"),
            "genres": [{"name": "Drama"}],
            "rating": 8.0,
        }


def test_movies_phase1_home_and_detail_screenshots(page, live_app, app):
    poster = _art("DRAGON", "#22162d", "#c5294f")
    backdrop = _art("CINEMA", "#120c28", "#7b243e")
    backdrop_two = _art("SECOND", "#101d2b", "#1f8a70")
    with app.app_context():
        resume = Movie(
            title="Resume Feature",
            normalized_title="resume feature",
            media_type="movie",
            year=2024,
            status="watching",
            poster_url=poster,
            overview="A local feature ready to continue.",
            external_ids={"tmdb_id": "700", "tmdb_type": "movie"},
            metadata_state={
                "tmdb_detail": {"backdrop_url": backdrop, "tmdb_rating": 8.2},
                "tmdb_enrichment": {
                    "release_date": "2024-06-01",
                    "production_companies": [{"name": "Dragon Pictures", "logo_url": ""}],
                },
            },
        )
        resume_two = Movie(
            title="Second Resume Feature",
            normalized_title="second resume feature",
            media_type="movie",
            year=2023,
            status="watching",
            poster_url=poster,
            overview="A second local feature proving the hero can rotate.",
            external_ids={"tmdb_id": "705", "tmdb_type": "movie"},
            metadata_state={"tmdb_detail": {"backdrop_url": backdrop_two}},
        )
        want = Movie(
            title="Want To Watch Feature",
            normalized_title="want to watch feature",
            media_type="movie",
            year=2025,
            status="want_to_watch",
            poster_url=poster,
            overview="A saved title ready for a deliberate first watch.",
            external_ids={"tmdb_id": "706", "tmdb_type": "movie"},
        )
        anchor = Movie(
            title="Watched Anchor",
            normalized_title="watched anchor",
            media_type="movie",
            year=2022,
            status="watched",
            poster_url=poster,
            external_ids={"tmdb_id": "701", "tmdb_type": "movie"},
            metadata_state={
                "tmdb_detail": {
                    "backdrop_url": backdrop,
                    "recommendations": [
                        {
                            "tmdb_id": 702,
                            "media_type": "movie",
                            "title": "Recommendation One",
                            "poster_url": poster,
                            "year": 2023,
                            "rating": 7.9,
                        }
                    ],
                    "trailers": [
                        {
                            "name": "Official Trailer",
                            "url": "https://www.youtube.com/watch?v=phase1",
                            "official": True,
                        }
                    ],
                    "reviews": [
                        {
                            "author": "Reviewer",
                            "content": (
                                "A long review used to verify the compact default presentation."
                            ),
                            "url": "",
                        }
                    ],
                    "similar": [
                        {
                            "tmdb_id": 703,
                            "media_type": "movie",
                            "title": "Similar One",
                            "poster_url": poster,
                            "year": 2021,
                            "rating": 7.4,
                        }
                    ],
                },
                "tmdb_enrichment": {
                    "production_companies": [{"name": "Dragon Pictures", "logo_url": ""}]
                },
            },
            cast=[{"name": "Ada Example", "character": "Lead", "profile_url": poster}],
        )
        anchor_two = Movie(
            title="Second Anchor",
            normalized_title="second anchor",
            media_type="movie",
            year=2020,
            status="watched",
            poster_url=poster,
            metadata_state={
                "tmdb_detail": {
                    "recommendations": [
                        {
                            "tmdb_id": 704,
                            "media_type": "movie",
                            "title": "Recommendation Two",
                            "poster_url": poster,
                            "year": 2020,
                            "rating": 7.2,
                        }
                    ]
                }
            },
        )
        db.session.add_all([resume, resume_two, want, anchor, anchor_two])
        db.session.flush()
        db.session.add(
            MovieProgress(movie_id=resume.id, current_seconds=600, duration_seconds=1800)
        )
        db.session.add(
            MovieProgress(movie_id=resume_two.id, current_seconds=420, duration_seconds=1500)
        )
        db.session.commit()
        anchor_id = anchor.id
        app.extensions["dragon_tmdb_catalog_provider"] = Phase1Provider()
        app.config.update(DRAGON_PLAYBACK_ENABLED=True, DRAGON_VIDSRC_ENABLED=True)

    page.set_viewport_size({"width": 1280, "height": 900})
    evidence_dir = Path(r"C:\Users\walid\Pictures\movies-v2-phase1")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    _sign_in(page, live_app)
    page.goto(f"{live_app}/movies?because={anchor_id}")
    page.locator(".movie-provider-browser").wait_for()
    assert page.get_by_role("heading", name="Choose a provider").is_visible()
    assert (
        page.get_by_role("link", name="Browse titles available on Netflix").get_attribute(
            "aria-current"
        )
        == "true"
    )
    assert page.get_by_role("heading", name="Movies on Netflix").is_visible()
    assert page.get_by_role("heading", name="TV Series on Netflix").is_visible()
    assert page.get_by_role("heading", name="Because you watched Watched Anchor").is_visible()
    provider_selector = page.locator(".movie-provider-selector").first
    provider_selector.locator("summary").click()
    assert provider_selector.get_by_role("menu").is_visible()
    page.screenshot(
        path=str(evidence_dir / "I-provider-selector-open.png"),
        full_page=True,
    )
    provider_selector.locator("summary").click()
    page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
    nav_top = page.locator(".movie-v2-nav").bounding_box()["y"]
    assert 120 <= nav_top <= 140
    page.evaluate("window.scrollTo(0, 0)")
    hero_dots = page.locator("[data-home-hero-dot]")
    assert hero_dots.count() >= 2
    phase1_dir = evidence_dir
    page.screenshot(path=str(phase1_dir / "A-home-hero-candidate-a.png"), full_page=True)
    hero_title = page.locator("[data-home-focus-title]")
    first_hero_title = hero_title.inner_text()
    page.locator("[data-home-hero-next]").click()
    page.wait_for_function(
        "first => document.querySelector('[data-home-focus-title]')?.textContent !== first",
        arg=first_hero_title,
    )
    assert hero_title.inner_text() != first_hero_title
    page.screenshot(path=str(phase1_dir / "A-home-hero-candidate-b.png"), full_page=True)
    selector = page.locator("#because-anchor")
    assert selector.is_visible()
    selector.select_option(label="Second Anchor")
    page.locator(".movie-because-selector").evaluate("form => form.requestSubmit()")
    page.wait_for_url("**/movies?because=*")
    page.get_by_role("heading", name="Because you watched Second Anchor").wait_for()
    page.screenshot(path=str(phase1_dir / "L-because-you-watched-changed.png"), full_page=True)
    page.screenshot(path=str(phase1_dir / "A-home-hero-continue.png"), full_page=True)
    page.locator(".movie-want").screenshot(path=str(phase1_dir / "G-want-to-watch.png"))
    captures = {
        "B-browse-by-provider.png": ".movie-provider-browser",
        "C-because-selector.png": ".movie-because-selector",
        "D-movies-on-provider.png": "[data-discovery-rail='provider_movie']",
        "E-tv-on-provider.png": "[data-discovery-rail='provider_tv']",
        "F-generic-discovery-rail.png": "[data-discovery-rail='trending_movies']",
        "G-top-10.png": "[data-discovery-rail='top_10_movies']",
    }
    selector.click()
    page.screenshot(path=str(phase1_dir / "C-because-selector-open-attempt.png"))
    page.keyboard.press("Escape")
    for filename, selector in captures.items():
        locator = page.locator(selector).first
        assert locator.is_visible(), f"missing screenshot surface: {selector}"
        locator.screenshot(path=str(phase1_dir / filename))
    page.screenshot(path=str(phase1_dir / "home-desktop.png"), full_page=True)
    page.get_by_role("link", name="Browse titles available on Netflix").click()
    page.wait_for_url(f"{live_app}/movies?provider=8&region=US")
    assert page.get_by_role("heading", name="Movies on Netflix").is_visible()
    page.goto(f"{live_app}/movies?provider=9&region=US")
    assert page.get_by_role("heading", name="Movies on Prime Video").is_visible()
    assert page.get_by_role("heading", name="TV Series on Prime Video").is_visible()

    page.goto(f"{live_app}/movies/discover/movie/801")
    preview = page.locator("[data-discover-player]")
    preview.wait_for()
    assert page.locator("[data-preview-viewport]").is_hidden()
    page.screenshot(path=str(phase1_dir / "U-preview-player-on-demand.png"), full_page=True)

    page.goto(f"{live_app}/movies/{anchor_id}")
    page.locator(".movie-detail__related-rail").wait_for()
    assert page.get_by_text("More details").is_visible()
    assert page.locator(".movie-detail__trailer-art").count() == 1
    assert page.locator(".movie-detail__review-copy").count() == 1
    assert page.locator(".movie-detail__cast-rail").count() == 1
    assert page.get_by_text("Ada Example").is_visible()
    detail_captures = {
        "H-detail-hero.png": ".movie-detail__content--hero",
        "I-detail-metadata-transition.png": ".movie-detail__content--secondary",
        "J-cast.png": ".movie-detail__cast",
        "K-trailers.png": ".movie-detail__media-rail",
        "L-reviews.png": ".movie-detail__reviews",
        "M-more-like-this.png": ".movie-detail__related",
        "N-watch-options.png": ".movie-release-browser",
    }
    for filename, selector in detail_captures.items():
        locator = page.locator(selector).first
        assert locator.is_visible(), f"missing screenshot surface: {selector}"
        locator.screenshot(path=str(phase1_dir / filename))
    page.screenshot(path=str(phase1_dir / "detail-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{live_app}/movies?because={anchor_id}")
    page.locator(".movie-provider-browser").wait_for()
    page.locator(".movie-provider-browser__tile").first.wait_for()
    mobile_next = page.locator(".movie-provider-browser .movie-rail__control").last
    if mobile_next.is_visible() and not mobile_next.is_disabled():
        rail = page.locator(".movie-provider-browser__rail")
        before = rail.evaluate("element => element.scrollLeft")
        mobile_next.click()
        page.wait_for_timeout(250)
        assert rail.evaluate("element => element.scrollLeft") > before
    page.screenshot(path=str(phase1_dir / "O-home-mobile.png"), full_page=True)
    page.goto(f"{live_app}/movies/{anchor_id}")
    page.locator(".movie-detail__related-rail").wait_for()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )
    page.screenshot(path=str(phase1_dir / "P-detail-mobile.png"), full_page=True)
    page.locator(".movie-detail__related").screenshot(
        path=str(phase1_dir / "Q-detail-lower-mobile.png")
    )
    page.screenshot(path=str(phase1_dir / "detail-mobile.png"), full_page=True)
    for width in (390, 768, 1024, 1280, 1440):
        page.set_viewport_size({"width": width, "height": 844})
        page.goto(f"{live_app}/movies?because={anchor_id}")
        page.locator(".movie-provider-browser").wait_for()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
        )
    page.set_viewport_size({"width": 1280, "height": 844})
    page.goto(f"{live_app}/movies/library")
    page.get_by_role("heading", name="My Library").wait_for()
    assert page.locator("#movie-library").count() == 0
    page.screenshot(path=str(phase1_dir / "O-library-top.png"), full_page=True)
    page.locator(".filter-bar").screenshot(path=str(phase1_dir / "P-library-filters.png"))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{live_app}/movies/library")
    page.get_by_role("heading", name="My Library").wait_for()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )
    page.screenshot(path=str(phase1_dir / "AG-library-mobile.png"), full_page=True)
    assert not page_errors, page_errors
