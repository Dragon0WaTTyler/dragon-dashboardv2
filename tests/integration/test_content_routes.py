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
            title="مقال محفوظ محلياً",
            url="https://example.test/article",
            excerpt="Stored locally.",
            image_url="https://images.example.test/article.jpg",
        )
        book = Book(
            title="A Local Book",
            normalized_title="a local book",
            authors=["Example Author"],
            status="reading",
            page_count=300,
            current_page=25,
            cover_url="https://images.example.test/book.jpg",
        )
        db.session.add_all([video, source, article, book])
        db.session.commit()
        return {"video": video.id, "article": article.id, "book": book.id}


def test_primary_content_pages_render(authenticated_client, app):
    ids = seed_content(app)
    pages = {
        "/youtube?source=pockettube&group=Learning": "A focused lesson",
        f"/youtube/{ids['video']}": "Calm Channel",
        "/reading": "مقال محفوظ محلياً",
        f"/reading/{ids['article']}": "Stored locally.",
        "/books": "A Local Book",
        f"/books/{ids['book']}": "Example Author",
        "/": "A Local Book",
    }
    for path, expected in pages.items():
        response = authenticated_client.get(path)
        assert response.status_code == 200
        assert expected in response.get_data(as_text=True)


def test_books_grid_and_reading_thumbnails_render(authenticated_client, app):
    seed_content(app)
    grid = authenticated_client.get("/books?view=grid")
    compact = authenticated_client.get("/books?view=list")
    invalid = authenticated_client.get("/books?view=unknown")
    reading = authenticated_client.get("/reading")

    assert 'class="book-grid"' in grid.get_data(as_text=True)
    assert "book-grid--list" in compact.get_data(as_text=True)
    assert "book-grid--list" not in invalid.get_data(as_text=True)
    assert 'src="https://images.example.test/article.jpg"' in reading.get_data(as_text=True)
    assert 'dir="auto"' in reading.get_data(as_text=True)


def test_watch_later_paginates_large_playlists(authenticated_client, app):
    with app.app_context():
        db.session.add_all(
            [
                YouTubeVideo(
                    external_id=f"watch-{index}",
                    source="watch_later",
                    title=f"Watch video {index}",
                    position=index,
                )
                for index in range(51)
            ]
        )
        db.session.commit()

    first = authenticated_client.get("/youtube?source=watch_later&per_page=50")
    second = authenticated_client.get("/youtube?source=watch_later&per_page=50&page=2")

    assert ">Next</a>" in first.get_data(as_text=True)
    assert "Watch video 50" in second.get_data(as_text=True)
    assert ">Previous</a>" in second.get_data(as_text=True)


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
