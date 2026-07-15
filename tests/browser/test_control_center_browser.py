from tests.browser.test_shell import sign_in


def assert_no_horizontal_overflow(page):
    metrics = page.evaluate(
        """() => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
        })"""
    )
    assert metrics["scrollWidth"] == metrics["clientWidth"]


def test_control_center_desktop_registry_and_mobile_section_controls(page, live_app):
    page.set_viewport_size({"width": 1440, "height": 960})
    sign_in(page, live_app)
    page.goto(f"{live_app}/admin")

    assert page.get_by_role("heading", name="Control Center", level=1).count() == 1
    assert page.locator(".section-pulse").count() == 10
    assert page.get_by_text("Section registry", exact=True).count() == 1
    assert_no_horizontal_overflow(page)

    page.get_by_role("link", name="Movies Local watch library", exact=False).click()
    assert page.get_by_role("heading", name="Movies", level=1).count() == 1
    assert page.get_by_role("heading", name="Shape this section", level=2).count() == 1

    page.set_viewport_size({"width": 390, "height": 844})
    page.reload()
    assert page.locator(".preference-switch", has_text="Primary navigation").count() == 1
    assert page.locator(".preference-switch", has_text="Today workspace").count() == 1
    assert_no_horizontal_overflow(page)
