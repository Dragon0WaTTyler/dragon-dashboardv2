from app.books.models import Book
from app.extensions import db
from app.reading.models import Article, ReadingSource
from app.youtube.models import YouTubeVideo
from tests.conftest import csrf_from


def seed_content(app) -> dict[str, str]:
    with app.app_context():
        video = YouTubeVideo(
            external_id="yt-seed",
            source="pockettube",
            group_name="Learning",
            channel_title="Calm Channel",
            title="A focused lesson",
        )
        source = ReadingSource(name="Example Journal", feed_url="https://example.test/feed.xml")
        article = Article(
            source=source,
            title="An offline article",
            url="https://example.test/article",
            excerpt="Stored locally.",
        )
        book = Book(
            title="A Local Book",
            normalized_title="a local book",
            authors=["Example Author"],
            status="reading",
            page_count=300,
            current_page=25,
        )
        db.session.add_all([video, source, article, book])
        db.session.commit()
        return {"video": video.id, "article": article.id, "book": book.id}


def test_primary_content_pages_render(authenticated_client, app):
    ids = seed_content(app)
    pages = {
        "/youtube?source=pockettube&group=Learning": "A focused lesson",
        f"/youtube/{ids['video']}": "Calm Channel",
        "/reading": "An offline article",
        f"/reading/{ids['article']}": "Stored locally.",
        "/books": "A Local Book",
        f"/books/{ids['book']}": "Example Author",
        "/": "A Local Book",
    }
    for path, expected in pages.items():
        response = authenticated_client.get(path)
        assert response.status_code == 200
        assert expected in response.get_data(as_text=True)


def test_fulltext_status_get_is_read_only(authenticated_client, app):
    article_id = seed_content(app)["article"]
    with app.app_context():
        before = db.session.get(Article, article_id).updated_at
    response = authenticated_client.get(f"/reading/{article_id}/fulltext-status")
    assert response.status_code == 200
    assert response.get_json()["state"] == "not_requested"
    with app.app_context():
        assert db.session.get(Article, article_id).updated_at == before


def test_explicit_fulltext_post_is_safe_when_disabled(authenticated_client, app):
    article_id = seed_content(app)["article"]
    page = authenticated_client.get(f"/reading/{article_id}")
    response = authenticated_client.post(
        f"/reading/{article_id}/extract-fulltext",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )
    assert "Full-text extraction is unavailable" in response.get_data(as_text=True)
    with app.app_context():
        article = db.session.get(Article, article_id)
        assert article.fulltext_state == "not_requested"
        assert article.content_text == ""
