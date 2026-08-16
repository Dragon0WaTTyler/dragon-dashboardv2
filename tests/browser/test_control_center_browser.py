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

    assert page.get_by_role("heading", name="Settings", level=1).count() == 1
    assert page.locator('a[href^="/admin/sections/"]').count() == 10
    assert page.get_by_text("What do you want to change?", exact=True).count() == 1
    assert_no_horizontal_overflow(page)

    page.locator('a[href="/admin/sections/movies"]').click()
    assert page.get_by_role("heading", name="Movies", level=1).count() == 1
    assert page.get_by_role("heading", name="Access & placement", level=2).count() == 1

    page.set_viewport_size({"width": 390, "height": 844})
    page.reload()
    assert page.locator(".preference-switch", has_text="Primary navigation").count() == 1
    assert page.locator(".preference-switch", has_text="Show on Home").count() == 1
    assert_no_horizontal_overflow(page)


def test_tv_and_news_source_managers_are_responsive(page, live_app):
    page.set_viewport_size({"width": 1440, "height": 960})
    sign_in(page, live_app)

    page.goto(f"{live_app}/admin/sections/mytv")
    assert page.get_by_role("heading", name="Channel sources", level=2).count() == 1
    assert page.locator("summary", has_text="Add source").count() == 1
    assert page.get_by_role("heading", name="Channel categories", level=2).count() == 1
    assert_no_horizontal_overflow(page)

    page.goto(f"{live_app}/admin/sections/reading")
    assert page.get_by_role("heading", name="RSS & Atom feeds", level=2).count() == 1
    assert page.locator("summary", has_text="Add RSS source").count() == 1
    assert page.get_by_role("heading", name="Feed categories", level=2).count() == 1

    page.set_viewport_size({"width": 390, "height": 844})
    page.reload()
    assert_no_horizontal_overflow(page)
