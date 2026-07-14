import pytest

from app.books.models import Book
from app.books.services import BookService
from app.extensions import db
from app.reading.models import Article
from app.reading.services import ReadingService
from app.youtube.models import YouTubeVideo
from app.youtube.services import YouTubeService


def test_watch_later_removal_preserves_local_history(app):
    with app.app_context():
        video = YouTubeVideo(
            external_id="video-1", source="watch_later", title="Study session"
        )
        db.session.add(video)
        db.session.commit()
        YouTubeService.set_watched(video, True)
        YouTubeService.remove_from_watch_later(video)
        assert video.removed_from_source is True
        assert [event["event"] for event in video.local_history] == ["watched", "removed"]


def test_reading_status_and_status_projection(app):
    with app.app_context():
        article = Article(title="Local first", url="https://example.test/article")
        db.session.add(article)
        db.session.commit()
        ReadingService.set_status(article, "reading")
        projection = ReadingService.extraction_status(article)
        assert article.status == "reading"
        assert projection == {
            "article_id": article.id,
            "state": "not_requested",
            "error": None,
            "cached": False,
        }


def test_book_progress_range_is_validated(app):
    with app.app_context():
        book = Book(title="The Book", normalized_title="the book", page_count=200)
        db.session.add(book)
        db.session.commit()
        BookService.save_progress(book, status="reading", current_page=45)
        assert book.current_page == 45
        with pytest.raises(ValueError):
            BookService.save_progress(book, status="reading", current_page=201)


def test_book_quote_is_linked_and_validated(app):
    with app.app_context():
        book = Book(title="Quoted", normalized_title="quoted", page_count=100)
        db.session.add(book)
        db.session.commit()
        quote = BookService.add_quote(book, text="  A useful   thought. ", page=20)
        assert quote.text == "A useful thought."
        assert quote.book_id == book.id
        with pytest.raises(ValueError):
            BookService.add_quote(book, text="", page=None)
        with pytest.raises(ValueError):
            BookService.add_quote(book, text="Too far", page=101)


def test_explicit_fulltext_extraction_uses_injected_adapter(app):
    class Extractor:
        def extract(self, url):
            assert url == "https://example.test/article"
            return {"content_text": "Full local article text."}

    with app.app_context():
        article = Article(title="Extract", url="https://example.test/article")
        db.session.add(article)
        db.session.commit()
        ReadingService.extract_fulltext(article, Extractor())
        assert article.content_text == "Full local article text."
        assert article.fulltext_state == "cached"
        assert article.status == "reading"
