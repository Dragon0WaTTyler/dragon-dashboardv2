import pytest

from app.books.models import Book, Quote
from app.extensions import db

pytestmark = pytest.mark.browser


def sign_in(page, base_url: str):
    page.goto(f"{base_url}/auth/login")
    page.get_by_label("Username").fill("walid")
    page.get_by_label("Password").fill("correct horse battery staple")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"{base_url}/")


def test_arabic_book_detail_shows_cover_and_rtl_layout(page, live_app, app):
    image = (
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
        "width='360' height='540'%3E%3Crect width='360' height='540' "
        "fill='%237d1725'/%3E%3C/svg%3E"
    )
    with app.app_context():
        book = Book(
            title="كويكول",
            normalized_title="كويكول",
            authors=["حنان لاشين"],
            description="رواية عربية محفوظة في المكتبة المحلية.",
            cover_url=image,
            status="reading",
            current_page=84,
            page_count=320,
            published_year=2021,
        )
        book.quotes.append(
            Quote(text="أحياناً نلتقي بقلوب كالصخور، بل هي أشد قسوة.", page=41)
        )
        db.session.add(book)
        db.session.commit()
        book_id = book.id

    page.set_viewport_size({"width": 1440, "height": 900})
    sign_in(page, live_app)
    page.goto(f"{live_app}/books/{book_id}")

    assert page.locator(".book-detail__cover img").is_visible()
    metrics = page.locator(".book-detail__hero").evaluate(
        "element => {"
        "const cover = element.querySelector('.book-detail__cover').getBoundingClientRect();"
        "const intro = element.querySelector('.book-detail__intro').getBoundingClientRect();"
        "const title = element.querySelector('h1');"
        "return {"
        "coverLeft: cover.left, introLeft: intro.left,"
        "direction: getComputedStyle(title).direction,"
        "textAlign: getComputedStyle(title).textAlign"
        "};"
        "}"
    )
    assert metrics["coverLeft"] > metrics["introLeft"]
    assert metrics["direction"] == "rtl"
    assert metrics["textAlign"] == "right"
    quote = page.locator(".quote-list blockquote").first
    assert quote.evaluate("element => getComputedStyle(element).direction") == "rtl"
    assert quote.evaluate("element => getComputedStyle(element).textAlign") == "right"

    page.set_viewport_size({"width": 390, "height": 844})
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow == 0
