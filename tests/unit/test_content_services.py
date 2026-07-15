from datetime import UTC, datetime, timedelta

import pytest

from app.books.models import Book
from app.books.services import BookService
from app.extensions import db
from app.movies.models import Movie
from app.reading.models import Article
from app.reading.services import ReadingService, article_item
from app.reading.text import normalize_article_text
from app.shared.text import text_direction
from app.today.services import TodayService
from app.youtube.models import YouTubeVideo
from app.youtube.services import YouTubeService, video_item


def test_content_direction_detects_arabic_and_mixed_titles():
    assert text_direction("A plain English title") == "ltr"
    assert text_direction("عنوان عربي") == "rtl"
    assert text_direction("Editing tutorial · شرح عربي") == "rtl"
    assert video_item(YouTubeVideo(title="فيديو عربي"))["direction"] == "rtl"
    assert article_item(Article(title="مقال عربي", url="https://example.test"))[
        "direction"
    ] == "rtl"


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


def test_shuffle_happens_before_playlist_pagination(app):
    with app.app_context():
        db.session.add_all(
            [
                YouTubeVideo(
                    external_id=f"shuffle-{index}",
                    source="watch_later",
                    title=f"Shuffle video {index}",
                    position=index,
                )
                for index in range(120)
            ]
        )
        db.session.commit()

        first = YouTubeService.feed(
            source="watch_later", order="shuffle", limit=50, offset=0, seed="fixed-seed"
        )
        second = YouTubeService.feed(
            source="watch_later", order="shuffle", limit=50, offset=50, seed="fixed-seed"
        )
        first_ids = {item["external_id"] for item in first["items"]}
        second_ids = {item["external_id"] for item in second["items"]}

        assert first["total"] == 120
        assert first["seed"] == second["seed"] == "fixed-seed"
        assert len(first_ids) == len(second_ids) == 50
        assert first_ids.isdisjoint(second_ids)
        assert any(int(video_id.removeprefix("shuffle-")) >= 50 for video_id in first_ids)


def test_today_live_rotation_changes_movie_hourly_and_youtube_every_five_minutes(app):
    with app.app_context():
        movies = [
            Movie(
                title=f"Rotating movie {index}",
                normalized_title=f"rotating movie {index}",
                year=2000 + index,
                runtime_minutes=100,
                status="want_to_watch",
                category="movie",
                source="My library",
                overview="A complete local movie record.",
                poster_url=f"https://images.example.test/movie-{index}.jpg",
                genres=[{"name": "Drama"}],
                directors=[{"name": f"Director {index}"}],
            )
            for index in range(3)
        ]
        videos = [
            YouTubeVideo(
                external_id=f"today-video-{index}",
                source="watch_later",
                title=f"Today video {index}",
                position=index,
            )
            for index in range(12)
        ]
        db.session.add_all([*movies, *videos])
        db.session.commit()
        moment = datetime(2026, 7, 15, 10, 1, tzinfo=UTC)

        first = TodayService.live_rotation(moment)
        next_mix = TodayService.live_rotation(moment + timedelta(minutes=5))
        next_movie = TodayService.live_rotation(moment + timedelta(hours=1))

        assert first["recommended_movie"]["id"] != next_movie["recommended_movie"]["id"]
        first_video_ids = {item["id"] for item in first["latest_youtube"]}
        next_video_ids = {item["id"] for item in next_mix["latest_youtube"]}
        assert len(first_video_ids) == len(next_video_ids) == 4
        assert first_video_ids.isdisjoint(next_video_ids)
        assert first["rotation"]["movie_interval_seconds"] == 3600
        assert first["rotation"]["youtube_interval_seconds"] == 300


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


def test_article_text_normalizer_cleans_escaped_breaks_and_markup():
    dirty = (
        "الفقرة الأولى&lt;br&gt;&lt;br&gt;الفقرة الثانية"
        "<script>hidden tracker</script><p>الفقرة الأخيرة</p>"
    )

    cleaned = normalize_article_text(dirty)

    assert "الفقرة الأولى\n\nالفقرة الثانية" in cleaned
    assert "الفقرة الأخيرة" in cleaned
    assert "<br>" not in cleaned
    assert "hidden tracker" not in cleaned


def test_watch_later_sync_keeps_pockettube_membership_separate(app):
    class Client:
        def fetch_playlist(self, playlist_id, *, maximum):
            assert playlist_id == "PL-test-playlist-123"
            assert maximum == 5000
            return [
                {
                    "id": "playlist-item-1",
                    "snippet": {
                        "title": "درس عربي",
                        "description": "وصف",
                        "position": 0,
                        "resourceId": {"videoId": "shared-video"},
                        "videoOwnerChannelTitle": "Channel",
                        "thumbnails": {
                            "high": {"url": "https://images.example.test/video.jpg"}
                        },
                    },
                }
            ]

    with app.app_context():
        db.session.add(
            YouTubeVideo(
                external_id="shared-video",
                source="pockettube",
                group_name="Learning",
                title="PocketTube copy",
            )
        )
        db.session.commit()

        counts = YouTubeService.sync_watch_later(Client(), "PL-test-playlist-123")
        rows = list(
            db.session.scalars(
                db.select(YouTubeVideo).where(YouTubeVideo.external_id == "shared-video")
            )
        )

        assert counts == {"created": 1, "updated": 0, "removed": 0, "videos": 1}
        assert {row.source for row in rows} == {"pockettube", "watch_later"}
        watch_later = next(row for row in rows if row.source == "watch_later")
        assert watch_later.thumbnail_url == "https://images.example.test/video.jpg"
