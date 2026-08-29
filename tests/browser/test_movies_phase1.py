from __future__ import annotations

from pathlib import Path

import pytest

from app.extensions import db
from app.movies.models import Movie, MovieLibraryEntry, MovieProgress

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


def _assert_canonical_series_hero(page) -> None:
    """Saved and stateless series must use the same single-overlay hero."""
    styles = page.locator(".movie-detail.movie-discover-hero.movie-cinematic-hero").evaluate(
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
    )
    assert styles == {
        "minHeight": "760px",
        "backdropOpacity": "1",
        "backdropMask": "none",
        "heroBefore": "none",
        "backdropAfter": "none",
    }


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
                for index in range(1, 31)
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
        item = {
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
        if media_type == "tv":
            item.update(
                {
                    "title": "The Blacklist",
                    "year": 2013,
                    "original_title": "The Blacklist",
                    "runtime_minutes": 43,
                    "cast": [
                        {
                            "name": "James Spader",
                            "character": "Raymond Reddington",
                            "profile_url": _art("CAST", "#182538", "#7d405f"),
                        }
                    ],
                    "seasons": [
                        {
                            "season_number": 1,
                            "name": "Season 1",
                            "episode_count": 22,
                            "poster_url": _art("S1", "#182538", "#7d405f"),
                        }
                    ],
                    "tmdb_detail": {
                        "tagline": "The blacklist is just the beginning.",
                        "certification": "TV-14",
                        "original_language": "en",
                        "countries": ["United States"],
                        "tmdb_rating": 8.0,
                        "trailers": [
                            {
                                "name": "Official Trailer",
                                "url": "https://www.youtube.com/watch?v=blacklist",
                                "official": True,
                            }
                        ],
                        "reviews": [
                            {
                                "author": "TMDB member",
                                "content": "A rich series review for the comparison surface.",
                                "url": "",
                            }
                        ],
                        "similar": [
                            {
                                "tmdb_id": 902,
                                "media_type": "tv",
                                "title": "Similar Series",
                                "poster_url": _art("SIMILAR", "#182538", "#7d405f"),
                                "year": 2014,
                                "rating": 7.7,
                            }
                        ],
                    },
                }
            )
        return item


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

    page.set_viewport_size({"width": 1600, "height": 900})
    evidence_dir = Path(r"C:\Users\walid\Pictures\movies-v2-phase1")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    phase1_dir = evidence_dir
    unified_dir = Path(r"C:\Users\walid\Pictures\movies-v2-unified-detail")
    unified_dir.mkdir(parents=True, exist_ok=True)
    closure_dir = Path(r"C:\Users\walid\Pictures\movies-v2-library-closure")
    closure_dir.mkdir(parents=True, exist_ok=True)
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
    canvas = page.locator(".page-frame").bounding_box()
    assert canvas is not None
    assert canvas["x"] == pytest.approx(0, abs=1)
    assert canvas["width"] >= 1598
    local_nav = page.locator(".movie-v2-nav")
    hero = page.locator(".movie-personal-hero")
    nav_box_before = local_nav.bounding_box()
    hero_box = hero.bounding_box()
    assert nav_box_before is not None and hero_box is not None
    assert local_nav.evaluate("element => getComputedStyle(element).position") == "fixed"
    assert hero_box["y"] <= nav_box_before["y"] + nav_box_before["height"]
    nav_x_before = nav_box_before["x"]
    page.screenshot(path=str(phase1_dir / "A-home-1600.png"), full_page=False)
    page.locator(".movie-now").first.scroll_into_view_if_needed()
    page.screenshot(path=str(phase1_dir / "B-home-rails-1600.png"), full_page=False)
    page.evaluate("window.scrollTo(0, 520)")
    page.screenshot(path=str(phase1_dir / "C-home-after-scroll-1600.png"), full_page=False)
    page.screenshot(path=str(phase1_dir / "B-home-after-scroll-1600.png"), full_page=False)
    provider_tv = page.locator("[data-discovery-rail='provider_tv']")
    provider_rail = provider_tv.locator("[data-movie-rail]")
    provider_controls = provider_tv.locator(".movie-rail__control")
    assert provider_rail.evaluate(
        "element => element.parentElement?.classList.contains('movie-rail-shell')"
    )
    assert provider_controls.first.evaluate(
        "element => element.parentElement?.classList.contains('movie-rail__controls')"
    )
    assert provider_controls.first.evaluate(
        "element => !element.closest('[data-movie-rail]')"
    )
    provider_rail_box = provider_rail.bounding_box()
    assert provider_rail_box is not None
    assert provider_controls.count() == 2
    left_control_box = provider_controls.first.bounding_box()
    right_control_box = provider_controls.last.bounding_box()
    assert left_control_box is not None and right_control_box is not None
    assert left_control_box["x"] <= provider_rail_box["x"] + 12
    assert (
        right_control_box["x"] + right_control_box["width"]
        >= provider_rail_box["x"] + provider_rail_box["width"] - 12
    )
    provider_tv.screenshot(path=str(phase1_dir / "E-provider-tv-start-1600.png"))
    provider_controls.last.click()
    page.wait_for_timeout(550)
    prev_x_before = left_control_box["x"]
    next_x_before = right_control_box["x"]
    prev_x_after_one = provider_controls.first.bounding_box()["x"]
    next_x_after_one = provider_controls.last.bounding_box()["x"]
    assert prev_x_after_one == pytest.approx(prev_x_before, abs=1)
    assert next_x_after_one == pytest.approx(next_x_before, abs=1)
    provider_tv.screenshot(path=str(phase1_dir / "F-provider-tv-after-one-1600.png"))
    for _ in range(8):
        if provider_controls.last.is_disabled():
            break
        provider_controls.last.click()
        page.wait_for_timeout(550)
    provider_tv.screenshot(path=str(phase1_dir / "G-provider-tv-after-several-1600.png"))
    prev_at_end = provider_controls.first.bounding_box()
    next_at_end = provider_controls.last.bounding_box()
    assert prev_at_end is not None and next_at_end is not None
    assert prev_at_end["x"] == pytest.approx(prev_x_before, abs=1)
    assert next_at_end["x"] == pytest.approx(next_x_before, abs=1)
    assert provider_controls.last.is_disabled()
    page.screenshot(path=str(phase1_dir / "H-provider-tv-end-1600.png"), full_page=False)
    page.wait_for_timeout(550)
    for _ in range(8):
        if provider_controls.first.is_disabled():
            break
        provider_controls.first.click()
        page.wait_for_timeout(550)
    prev_at_start = provider_controls.first.bounding_box()
    next_at_start = provider_controls.last.bounding_box()
    assert prev_at_start is not None and next_at_start is not None
    assert prev_at_start["x"] == pytest.approx(prev_x_before, abs=1)
    assert next_at_start["x"] == pytest.approx(next_x_before, abs=1)
    assert provider_controls.first.is_disabled()
    page.screenshot(path=str(phase1_dir / "I-provider-tv-back-start-1600.png"), full_page=False)
    page.evaluate("window.scrollTo(0, 0)")
    provider_selector = page.locator(".movie-provider-selector").first
    provider_selector.locator("summary").click()
    assert provider_selector.get_by_role("menu").is_visible()
    page.screenshot(
        path=str(evidence_dir / "I-provider-selector-open.png"),
        full_page=True,
    )
    provider_selector.locator("summary").click()
    page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
    page.wait_for_timeout(250)
    nav_top = page.locator(".movie-v2-nav").bounding_box()["y"]
    nav_after_scroll = page.locator(".movie-v2-nav").bounding_box()
    assert 120 <= nav_top <= 140
    assert nav_after_scroll is not None
    assert nav_after_scroll["x"] == pytest.approx(nav_x_before, abs=1)
    page.evaluate("window.scrollTo(0, 0)")
    hero_dots = page.locator("[data-home-hero-dot]")
    assert hero_dots.count() >= 2
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
    page.locator("[data-discovery-rail='trending_movies']").first.screenshot(
        path=str(phase1_dir / "J-generic-rail-1600.png")
    )
    page.screenshot(path=str(phase1_dir / "home-desktop.png"), full_page=True)
    page.screenshot(path=str(unified_dir / "M-home-fullbleed-1600.png"), full_page=False)
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
    page.screenshot(path=str(unified_dir / "I-external-movie-hero-1600.png"), full_page=False)
    page.locator(".movie-discover-detail").screenshot(
        path=str(unified_dir / "J-external-movie-lower-1600.png")
    )
    page.screenshot(path=str(closure_dir / "P-external-movie.png"), full_page=False)
    page.goto(f"{live_app}/movies/discover/tv/901")
    page.locator(".movie-discover-hero").wait_for()
    _assert_canonical_series_hero(page)
    assert page.get_by_role("heading", name="The Blacklist").is_visible()
    assert page.locator(".movie-detail__cast-rail").count() == 1
    assert page.locator(".movie-detail__media-rail").count() == 1
    assert page.locator(".movie-detail__reviews").count() == 1
    assert page.locator(".movie-detail__related-rail").count() == 1
    page.screenshot(path=str(closure_dir / "A-blacklist-discovery-hero.png"), full_page=False)
    page.locator(".movie-discover-detail").screenshot(
        path=str(closure_dir / "C-blacklist-discovery-modules.png")
    )
    page.screenshot(path=str(unified_dir / "K-external-tv-hero-1600.png"), full_page=False)
    if page.locator("[data-discover-player]").count():
        page.locator("[data-discover-player]").screenshot(
            path=str(unified_dir / "L-external-tv-preview-1600.png")
        )
    page.screenshot(path=str(closure_dir / "Q-external-tv.png"), full_page=False)

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
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(f"{live_app}/movies/{anchor_id}")
    page.locator(".movie-detail__related-rail").wait_for()
    page.screenshot(path=str(phase1_dir / "H-detail-1600.png"), full_page=False)
    page.screenshot(path=str(phase1_dir / "C-movie-detail-top-1600.png"), full_page=False)
    page.screenshot(path=str(unified_dir / "A-local-movie-hero-1600.png"), full_page=False)
    page.screenshot(path=str(unified_dir / "N-local-movie-fullbleed-1600.png"), full_page=False)
    page.locator(".movie-detail__quick-actions").screenshot(
        path=str(unified_dir / "B-local-movie-actions-1600.png")
    )
    page.screenshot(path=str(closure_dir / "A-local-movie-hero.png"), full_page=False)
    page.locator(".movie-detail__cast").screenshot(path=str(closure_dir / "B-local-movie-cast.png"))
    page.locator(".movie-detail__media-rail").screenshot(
        path=str(closure_dir / "C-local-movie-trailers.png")
    )
    page.locator(".movie-detail__content--secondary").scroll_into_view_if_needed()
    page.locator(".movie-detail__cast").screenshot(
        path=str(phase1_dir / "K-cast-more-like-this-1600.png")
    )
    page.screenshot(path=str(phase1_dir / "I-detail-lower-1600.png"), full_page=False)
    page.screenshot(path=str(unified_dir / "C-local-movie-lower-1600.png"), full_page=False)
    page.locator(".movie-detail__related").screenshot(
        path=str(closure_dir / "D-local-movie-related.png")
    )
    page.locator(".movie-detail__content--secondary").screenshot(
        path=str(closure_dir / "E-local-movie-metadata.png")
    )
    page.locator(".movie-detail__quick-actions").screenshot(
        path=str(closure_dir / "F-local-movie-personal-state.png")
    )
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
    page.screenshot(path=str(phase1_dir / "L-home-mobile-390.png"), full_page=False)
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
        if width == 1024:
            page.screenshot(path=str(phase1_dir / "M-home-1024.png"), full_page=False)
        if width == 390:
            page.screenshot(path=str(phase1_dir / "N-home-390.png"), full_page=False)
    page.set_viewport_size({"width": 1600, "height": 844})
    page.goto(f"{live_app}/movies/library")
    page.get_by_role("heading", name="My Library").wait_for()
    assert page.locator("#movie-library").count() == 0
    page.screenshot(path=str(phase1_dir / "O-library-top.png"), full_page=True)
    page.locator(".filter-bar").screenshot(path=str(phase1_dir / "P-library-filters.png"))
    page.screenshot(path=str(phase1_dir / "D-library-1600.png"), full_page=False)
    page.locator(".filter-bar").screenshot(path=str(phase1_dir / "E-library-filters-1600.png"))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{live_app}/movies/library")
    page.get_by_role("heading", name="My Library").wait_for()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )
    page.screenshot(path=str(phase1_dir / "AG-library-mobile.png"), full_page=True)
    page.screenshot(path=str(phase1_dir / "O-library-390.png"), full_page=False)


def test_chernobyl_series_detail_stays_compact_and_connected(page, live_app, app):
    poster = _art("CHERNOBYL", "#17283d", "#b9454f")
    backdrop = _art("REACTOR", "#111d2b", "#5c2839")
    episodes = {
        "1": [
            {
                "season_number": 1,
                "episode_number": number,
                "name": f"Episode {number}",
                "overview": "A concise episode synopsis.",
                "still_url": "",
                "runtime_minutes": 60,
                "air_date": "2019-05-06",
            }
            for number in range(1, 6)
        ]
    }
    metadata = {
        "tmdb_detail": {
            "backdrop_url": backdrop,
            "tagline": "What is the cost of lies?",
            "original_language": "en",
            "countries": ["United Kingdom"],
            "certification": "TV-MA",
            "tmdb_rating": 9.3,
            "trailers": [
                {
                    "name": "Official Trailer",
                    "url": "https://www.youtube.com/watch?v=chernobyl",
                    "official": True,
                }
            ],
            "reviews": [],
            "similar": [
                {
                    "tmdb_id": 87109,
                    "media_type": "tv",
                    "title": "Related Series",
                    "poster_url": poster,
                    "year": 2020,
                    "rating": 8.1,
                }
            ],
            "recommendations": [],
        },
        "tmdb_enrichment": {
            "release_date": "2019-05-06",
            "production_companies": [{"name": "HBO"}],
            "budget": None,
            "revenue": None,
        },
        "tv_total_seasons": 1,
        "tv_total_episodes": 5,
        "tv_seasons": [
            {
                "season_number": 1,
                "name": "Season 1",
                "episode_count": 5,
                "air_date": "2019-05-06",
                "poster_url": poster,
            }
        ],
        "tv_episodes": episodes,
    }
    with app.app_context():
        movie = Movie(
            title="Chernobyl",
            normalized_title="chernobyl",
            media_type="tv",
            year=2019,
            status="watching",
            poster_url=poster,
            overview="A disaster and its human cost.",
            genres=[{"name": "Drama"}],
            cast=[{"name": "Jared Harris", "character": "Valery Legasov", "profile_url": ""}],
            external_ids={"tmdb_id": "87108", "tmdb_type": "tv"},
            metadata_state=metadata,
        )
        db.session.add(movie)
        db.session.flush()
        db.session.add(
            MovieLibraryEntry(
                media_key=movie.media_key,
                movie_id=movie.id,
                lifecycle_status="watching",
            )
        )
        db.session.add(
            MovieProgress(
                movie_id=movie.id,
                season=1,
                episode=1,
                current_seconds=75,
                duration_seconds=7_200,
                completed=False,
            )
        )
        db.session.commit()
        movie_id = movie.id

    closure_dir = Path(r"C:\Users\walid\Pictures\movies-v2-library-closure")
    closure_dir.mkdir(parents=True, exist_ok=True)
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.set_viewport_size({"width": 1600, "height": 900})
    _sign_in(page, live_app)
    page.goto(f"{live_app}/movies/{movie_id}?season=1")
    page.locator(".tv-series-hero").wait_for()
    _assert_canonical_series_hero(page)
    page.locator(".tv-series-episode-preview").wait_for()

    resume = page.locator(".tv-series-resume-strip")
    seasons = page.locator(".tv-series-seasons")
    episode_section = page.locator(".tv-series-episode-preview")
    resume_box = resume.bounding_box()
    seasons_box = seasons.bounding_box()
    episode_box = episode_section.bounding_box()
    assert resume_box and seasons_box and episode_box
    assert 0 <= seasons_box["y"] - (resume_box["y"] + resume_box["height"]) <= 180
    assert 0 <= episode_box["y"] - (seasons_box["y"] + seasons_box["height"]) <= 180
    assert page.locator(".tv-episode-tile").count() == 5
    assert all(
        (card.bounding_box() or {}).get("width", 0) <= 520
        for card in page.locator(".tv-episode-tile").all()
    )
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )
    page.screenshot(path=str(closure_dir / "B-chernobyl-local-hero.png"), full_page=False)
    resume.screenshot(path=str(closure_dir / "R-chernobyl-resume.png"))
    seasons.screenshot(path=str(closure_dir / "I-chernobyl-season-selector.png"))
    seasons.screenshot(path=str(closure_dir / "E-chernobyl-seasons.png"))
    episode_section.screenshot(path=str(closure_dir / "J2-chernobyl-episode-browser.png"))
    episode_section.screenshot(path=str(closure_dir / "F-chernobyl-episodes.png"))
    page.locator(".movie-detail__content--secondary").screenshot(
        path=str(closure_dir / "D-chernobyl-metadata-modules.png")
    )
    if page.locator(".movie-detail__cast").count():
        page.locator(".movie-detail__cast").screenshot(
            path=str(closure_dir / "G-chernobyl-cast.png")
        )
    if page.locator(".movie-detail__media-rail").count():
        page.locator(".movie-detail__media-rail").screenshot(
            path=str(closure_dir / "H-chernobyl-trailers.png")
        )
    if page.locator(".movie-detail__related").count():
        page.locator(".movie-detail__related").screenshot(
            path=str(closure_dir / "I-chernobyl-more-like-this.png")
        )
    for width in (390, 768, 1024, 1280, 1440, 1600):
        page.set_viewport_size({"width": width, "height": 844})
        page.goto(f"{live_app}/movies/{movie_id}?season=1")
        page.locator(".movie-discover-hero").wait_for()
        page.locator(".tv-series-episode-preview").wait_for()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
        )
    page.locator(".tv-series-watch-options").screenshot(
        path=str(closure_dir / "K-chernobyl-lower-series.png")
    )
    assert not page_errors, page_errors
