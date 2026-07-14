import re

import pytest

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
