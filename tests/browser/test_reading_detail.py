import pytest

from app.extensions import db
from app.reading.models import Article, ReadingSource

pytestmark = pytest.mark.browser


def sign_in(page, base_url: str):
    page.goto(f"{base_url}/auth/login")
    page.get_by_label("Username").fill("walid")
    page.get_by_label("Password").fill("correct horse battery staple")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"{base_url}/")


def test_article_click_loads_a_responsive_rtl_reader(page, live_app, app):
    title = "المغرب يتعامل مع الترويج في آخر مباراة إعدادية قبل بداية كأس العالم"
    image = (
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
        "width='1200' height='675'%3E%3Crect width='1200' height='675' "
        "fill='%237d1725'/%3E%3C/svg%3E"
    )
    content = (
        "هذا نص المقال الكامل الذي تم تحميله بعد اختيار القارئ للمقال. "
        "يظهر المحتوى في مساحة قراءة هادئة بعرض مريح واتجاه صحيح للغة العربية."
        "&lt;br&gt;&lt;br&gt;"
        "وتبقى نسخة المقال محفوظة محلياً حتى تفتح الصفحة بسرعة في المرات المقبلة."
    )

    class Extractor:
        @staticmethod
        def extract(url):
            return {"content_text": content, "canonical_url": url}

    with app.app_context():
        source = ReadingSource(
            name="هسبريس",
            feed_url="https://example.test/arabic-feed",
        )
        article = Article(
            source=source,
            title=title,
            url="https://example.test/arabic-article",
            author="هيئة التحرير",
            excerpt="ملخص قصير للمقال قبل فتحه.",
            image_url=image,
        )
        db.session.add(article)
        db.session.commit()
        article_id = article.id
    app.extensions["dragon_article_extractor"] = Extractor()

    page.set_viewport_size({"width": 1440, "height": 900})
    sign_in(page, live_app)
    page.goto(f"{live_app}/reading?view=list")
    assert page.get_by_role("button", name="Sync articles").is_visible()
    page.get_by_role("link", name=title, exact=True).click()
    page.wait_for_url(f"{live_app}/reading/{article_id}")

    assert page.get_by_text("هذا نص المقال الكامل").is_visible()
    assert "<br>" not in page.locator(".article-body").inner_text()
    assert page.get_by_text("Load full article explicitly").count() == 0
    assert page.get_by_text("Full-text cache").count() == 0
    title_metrics = page.locator(".reading-detail h1").evaluate(
        "element => ({"
        "fontSize: parseFloat(getComputedStyle(element).fontSize),"
        "direction: getComputedStyle(element).direction"
        "})"
    )
    assert title_metrics["fontSize"] <= 56
    assert title_metrics["direction"] == "rtl"

    page.set_viewport_size({"width": 390, "height": 844})
    metrics = page.evaluate(
        "() => ({"
        "scrollWidth: document.documentElement.scrollWidth,"
        "clientWidth: document.documentElement.clientWidth"
        "})"
    )
    assert metrics["scrollWidth"] == metrics["clientWidth"]
