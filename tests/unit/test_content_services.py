import json
from datetime import UTC, datetime, timedelta

import pytest

from app.books.models import Book
from app.books.notion_sync import BookNotionSyncClient, _is_book_schema
from app.books.repositories import BookRepository
from app.books.services import BookService, book_item
from app.extensions import db
from app.shared.models import SnapshotRecord
from app.movies.models import Movie, MovieProgress
from app.reading.models import Article, ReadingSource
from app.reading.services import (
    ReadingService,
    article_content_is_readable,
    article_detail,
    article_item,
)
from app.reading.text import article_paragraphs, normalize_article_text
from app.shared.text import text_direction
from app.today.services import TodayService
from app.youtube.models import YouTubeVideo
from app.youtube.repositories import YouTubeRepository
from app.youtube.services import (
    YouTubeService,
    clean_video_title,
    description_view,
    format_duration,
    video_item,
)


def test_content_direction_detects_arabic_and_mixed_titles():
    assert text_direction("A plain English title") == "ltr"
    assert text_direction("عنوان عربي") == "rtl"
    assert text_direction("Editing tutorial · شرح عربي") == "rtl"
    assert video_item(YouTubeVideo(title="فيديو عربي"))["direction"] == "rtl"
    assert article_item(Article(title="مقال عربي", url="https://example.test"))[
        "direction"
    ] == "rtl"
    assert book_item(
        Book(title="كتاب عربي", normalized_title="كتاب عربي", authors=["كاتب عربي"])
    )["direction"] == "rtl"


def test_youtube_duration_labels_are_compact_and_tabular():
    assert format_duration(65) == "1:05"
    assert format_duration(4112) == "1:08:32"
    assert format_duration(0) == ""
    assert video_item(YouTubeVideo(title="Timed", duration_seconds=767))[
        "duration_label"
    ] == "12:47"


def test_youtube_titles_hide_hashtags_for_display():
    title = "محاضرة الطبيب بوعزة تاريخ الفلسفة #الفلسفة #اللغة_العربية #محاضرات"

    assert clean_video_title(title) == "محاضرة الطبيب بوعزة تاريخ الفلسفة"
    assert video_item(YouTubeVideo(title=title))["title"] == (
        "محاضرة الطبيب بوعزة تاريخ الفلسفة"
    )


def test_youtube_description_separates_chapters_and_preserves_rtl():
    shaped = description_view(
        "ملخص عربي للحلقة\n\n00:00 المقدمة\n03:15 الفصل الأول\nhttps://example.test/notes"
    )

    assert shaped["paragraphs"] == [
        {"text": "ملخص عربي للحلقة", "direction": "rtl"},
        {"text": "https://example.test/notes", "direction": "ltr"},
    ]
    assert shaped["chapters"] == [
        {"label": "المقدمة", "stamp": "00:00", "seconds": 0, "direction": "rtl"},
        {
            "label": "الفصل الأول",
            "stamp": "03:15",
            "seconds": 195,
            "direction": "rtl",
        },
    ]


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
        favorite_videos = [
            YouTubeVideo(
                external_id=f"favorite-video-{index}",
                source="pockettube",
                group_name="my favoret",
                title=f"Favorite video {index}",
                position=index,
            )
            for index in range(12)
        ]
        source = ReadingSource(name="Today reads", feed_url="https://reads.example.test/rss")
        articles = [
            Article(
                source=source,
                external_id=f"today-article-{index}",
                title=f"Today article {index}",
                url=f"https://reads.example.test/{index}",
                status="reading",
            )
            for index in range(12)
        ]
        db.session.add_all([*movies, *videos, *favorite_videos, source, *articles])
        db.session.commit()
        moment = datetime(2026, 7, 15, 10, 1, tzinfo=UTC)

        first = TodayService.live_rotation(moment)
        next_mix = TodayService.live_rotation(moment + timedelta(minutes=5))
        next_movie = TodayService.live_rotation(moment + timedelta(hours=1))

        assert first["recommended_movie"]["id"] != next_movie["recommended_movie"]["id"]
        first_video_ids = {item["id"] for item in first["latest_youtube"]}
        next_video_ids = {item["id"] for item in next_mix["latest_youtube"]}
        first_favorite_ids = {item["id"] for item in first["pockettube_favorite"]}
        next_favorite_ids = {item["id"] for item in next_mix["pockettube_favorite"]}
        first_article_ids = {item["id"] for item in first["news_mix"]}
        next_article_ids = {item["id"] for item in next_mix["news_mix"]}
        assert len(first_video_ids) == len(next_video_ids) == 4
        assert len(first_favorite_ids) == len(next_favorite_ids) == 4
        assert len(first_article_ids) == len(next_article_ids) == 4
        assert first_video_ids.isdisjoint(next_video_ids)
        assert first_favorite_ids.isdisjoint(next_favorite_ids)
        assert first_article_ids != next_article_ids
        assert first["rotation"]["movie_interval_seconds"] == 3600
        assert first["rotation"]["youtube_interval_seconds"] == 300
        assert first["rotation"]["reading_interval_seconds"] == 300


def test_today_live_rotation_uses_latest_news_section_articles(app):
    with app.app_context():
        source = ReadingSource(name="Today reads", feed_url="https://reads.example.test/rss")
        base = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
        articles = [
            Article(
                source=source,
                external_id=f"news-article-{index}",
                title=f"News article {index}",
                url=f"https://reads.example.test/news/{index}",
                status="unread",
                published_at=base + timedelta(minutes=index),
            )
            for index in range(30)
        ]
        db.session.add_all([source, *articles])
        db.session.commit()

        live = TodayService.live_rotation(datetime(2026, 7, 15, 10, 1, tzinfo=UTC))
        news_mix_titles = {item["title"] for item in live["news_mix"]}

        latest_titles = {f"News article {index}" for index in range(6, 30)}
        older_titles = {f"News article {index}" for index in range(6)}
        assert len(news_mix_titles) == 4
        assert news_mix_titles <= latest_titles
        assert news_mix_titles.isdisjoint(older_titles)


def test_today_workspace_surfaces_active_movie_or_series(app):
    with app.app_context():
        movie = Movie(
            title="Active Series",
            normalized_title="active series",
            year=2026,
            media_type="tv",
            status="watching",
            poster_url="https://images.example.test/active.jpg",
        )
        db.session.add(movie)
        db.session.flush()
        db.session.add(
            MovieProgress(
                movie_id=movie.id,
                season=1,
                episode=5,
                current_seconds=1200,
                duration_seconds=2400,
                completed=False,
            )
        )
        db.session.commit()

        workspace = TodayService.workspace()

        assert workspace["watching_now"]["title"] == "Active Series"
        assert workspace["watching_now"]["media_type"] == "tv"
        assert workspace["watching_now"]["progress"]["percent"] == 50
        assert workspace["watching_now"]["watch_target"] == {
            "season": 1,
            "episode": 5,
            "from_completed_episode": False,
        }


def test_today_workspace_advances_completed_episode_target(app):
    with app.app_context():
        movie = Movie(
            title="Active Series",
            normalized_title="active series",
            year=2026,
            media_type="tv",
            status="watching",
            poster_url="https://images.example.test/active.jpg",
        )
        db.session.add(movie)
        db.session.flush()
        db.session.add(
            MovieProgress(
                movie_id=movie.id,
                season=1,
                episode=5,
                current_seconds=2400,
                duration_seconds=2400,
                completed=True,
            )
        )
        db.session.commit()

        workspace = TodayService.workspace()

        assert workspace["continue_watching"] == []
        assert workspace["watching_now"]["title"] == "Active Series"
        assert workspace["watching_now"]["watch_target"] == {
            "season": 1,
            "episode": 6,
            "from_completed_episode": True,
        }


def test_today_workspace_prefers_latest_episode_progress_over_legacy_progress(app):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            year=1999,
            media_type="tv",
            status="watching",
            poster_url="https://images.example.test/sopranos.jpg",
        )
        db.session.add(movie)
        db.session.flush()
        db.session.add_all(
            [
                MovieProgress(
                    movie_id=movie.id,
                    current_seconds=2700,
                    duration_seconds=3600,
                    completed=False,
                    updated_at=datetime(2026, 7, 19, 7, 0, tzinfo=UTC),
                ),
                MovieProgress(
                    movie_id=movie.id,
                    season=1,
                    episode=6,
                    current_seconds=34,
                    duration_seconds=3000,
                    completed=False,
                    updated_at=datetime(2026, 7, 19, 7, 5, tzinfo=UTC),
                ),
            ]
        )
        db.session.commit()

        workspace = TodayService.workspace()

        assert workspace["watching_now"]["progress"]["season"] == 1
        assert workspace["watching_now"]["progress"]["episode"] == 6
        assert workspace["watching_now"]["progress"]["percent"] == 1
        assert workspace["watching_now"]["watch_target"] == {
            "season": 1,
            "episode": 6,
            "from_completed_episode": False,
        }


def test_today_workspace_exposes_multiple_reading_books_for_switcher(app):
    with app.app_context():
        older = Book(
            title="Older Reading Book",
            normalized_title="older reading book",
            authors=["First Author"],
            status="reading",
            current_page=45,
            page_count=300,
            updated_at=datetime(2026, 7, 19, 7, 0, tzinfo=UTC),
        )
        newer = Book(
            title="Newer Reading Book",
            normalized_title="newer reading book",
            authors=["Second Author"],
            status="reading",
            current_page=120,
            page_count=400,
            updated_at=datetime(2026, 7, 20, 7, 0, tzinfo=UTC),
        )
        wishlist = Book(
            title="Wishlist Book",
            normalized_title="wishlist book",
            status="wishlist",
        )
        db.session.add_all([older, newer, wishlist])
        db.session.commit()

        workspace = TodayService.workspace()

        assert [book["title"] for book in workspace["current_books"]] == [
            "Newer Reading Book",
            "Older Reading Book",
        ]
        assert workspace["current_book"]["title"] == "Newer Reading Book"
        assert workspace["current_books"][0]["progress_percent"] == 30


def test_today_workspace_falls_back_to_watching_status(app):
    with app.app_context():
        movie = Movie(
            title="The Sopranos",
            normalized_title="the sopranos",
            year=1999,
            media_type="tv",
            status="watching",
            poster_url="https://images.example.test/sopranos.jpg",
        )
        db.session.add(movie)
        db.session.commit()

        workspace = TodayService.workspace()

        assert workspace["watching_now"]["title"] == "The Sopranos"
        assert workspace["watching_now"]["media_type"] == "tv"
        assert workspace["watching_now"]["progress"] is None


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


def test_reading_sync_caps_feed_cache_at_200_articles(app):
    class Client:
        @staticmethod
        def fetch(url):
            assert url == "https://example.test/feed.xml"
            return {
                "entries": [
                    {
                        "external_id": f"article-{index:03d}",
                        "title": f"Article {index:03d}",
                        "url": f"https://example.test/{index:03d}",
                        "published_at": datetime(
                            2026, 7, 19, 12, index % 60, tzinfo=UTC
                        ),
                    }
                    for index in range(230)
                ]
            }

    with app.app_context():
        source = ReadingSource(
            name="Example Journal",
            feed_url="https://example.test/feed.xml",
        )
        db.session.add(source)
        db.session.commit()

        counts = ReadingService.sync_sources(Client())

        articles = db.session.scalars(db.select(Article)).all()
        assert len(articles) == 200
        assert counts["created"] == 230
        assert counts["trimmed"] == 30


def test_book_progress_range_is_validated(app):
    with app.app_context():
        book = Book(title="The Book", normalized_title="the book", page_count=200)
        db.session.add(book)
        db.session.commit()
        BookService.save_progress(book, status="reading", current_page=45)
        assert book.current_page == 45
        with pytest.raises(ValueError):
            BookService.save_progress(book, status="reading", current_page=201)


def test_book_progress_normalizes_legacy_wishlist_status(app):
    with app.app_context():
        book = Book(title="Future Shelf", normalized_title="future shelf", page_count=200)
        db.session.add(book)
        db.session.commit()

        BookService.save_progress(book, status="want_to_read", current_page=0)

        assert book.status == "wishlist"


def test_current_book_syncs_notion_progress_before_projection(app):
    class Client:
        configured = True

        def __init__(self) -> None:
            self.calls = 0

        def list_books(self):
            self.calls += 1
            return [
                {
                    "notion_page_id": "book-page-1",
                    "title": "الف شمس ساطعة",
                    "cover_url": "https://images.example.test/notion-cover.jpg",
                    "status": "Reading",
                    "page_count": 109,
                    "progress_percent": 15,
                }
            ]

    with app.app_context():
        book = Book(
            title="الف شمس ساطعة",
            normalized_title="الف شمس ساطعة",
            authors=["خالد حسيني"],
            status="reading",
            current_page=0,
            page_count=0,
            external_ids={"notion_page_id": "book-page-1"},
        )
        db.session.add(book)
        db.session.commit()
        client = Client()
        app.extensions["dragon_book_notion_sync_client"] = client

        current = BookService.current_book()

        assert client.calls == 1
        assert current is not None
        assert current["title"] == "الف شمس ساطعة"
        assert current["cover_url"] == "https://images.example.test/notion-cover.jpg"
        assert current["current_page"] == 16
        assert current["page_count"] == 109
        assert current["progress_percent"] == 15

        synced = db.session.get(Book, book.id)
        assert synced is not None
        assert synced.cover_url == "https://images.example.test/notion-cover.jpg"
        assert synced.current_page == 16
        assert synced.page_count == 109
        assert synced.external_ids["notion_page_id"] == "book-page-1"
        assert synced.metadata_state["notion_cover_url"] == (
            "https://images.example.test/notion-cover.jpg"
        )

        snapshot = db.session.scalar(
            db.select(SnapshotRecord).where(SnapshotRecord.domain == "books")
        )
        assert snapshot is not None
        assert snapshot.state == "fresh"


def test_current_book_uses_cached_notion_snapshot_with_naive_timestamp(
    app, monkeypatch
):
    class Client:
        configured = True

        def list_books(self):
            raise AssertionError("Fresh cached snapshots should skip Notion calls.")

    with app.app_context():
        book = Book(
            title="Cached Shelf",
            normalized_title="cached shelf",
            status="reading",
            current_page=12,
            page_count=120,
        )
        db.session.add(book)
        db.session.add(
            SnapshotRecord(
                domain="books",
                schema_version="books-notion-progress-v1",
                relative_path="notion://books",
                checksum="cached",
                state="fresh",
                message="Cached.",
                generated_at=datetime(2026, 7, 26, 14, 0),
                last_success_at=datetime(2026, 7, 26, 14, 0),
                updated_at=datetime(2026, 7, 26, 14, 0),
            )
        )
        db.session.commit()
        app.extensions["dragon_book_notion_sync_client"] = Client()
        monkeypatch.setattr(
            "app.books.notion_sync.utc_now",
            lambda: datetime(2026, 7, 26, 14, 1, tzinfo=UTC),
        )

        current = BookService.current_book()

        assert current is not None
        assert current["title"] == "Cached Shelf"


def test_book_search_force_syncs_and_creates_new_notion_book(app, monkeypatch):
    class Client:
        configured = True

        def __init__(self) -> None:
            self.calls = 0

        def list_books(self):
            self.calls += 1
            return [
                {
                    "notion_page_id": "new-book-page",
                    "notion_url": "https://notion.example.test/new-book-page",
                    "title": "Brand New Notion Book",
                    "authors": ["Notion Author"],
                    "cover_url": "https://images.example.test/new-book.jpg",
                    "status": "Reading",
                    "page_count": 240,
                    "progress_percent": 25,
                }
            ]

    with app.app_context():
        db.session.add(
            SnapshotRecord(
                domain="books",
                schema_version="books-notion-progress-v1",
                relative_path="notion://books",
                checksum="cached",
                state="fresh",
                message="Cached.",
                generated_at=datetime(2026, 7, 26, 14, 0),
                last_success_at=datetime(2026, 7, 26, 14, 0),
                updated_at=datetime(2026, 7, 26, 14, 0),
            )
        )
        db.session.commit()
        client = Client()
        app.extensions["dragon_book_notion_sync_client"] = client
        monkeypatch.setattr(
            "app.books.notion_sync.utc_now",
            lambda: datetime(2026, 7, 26, 14, 1, tzinfo=UTC),
        )

        results = BookRepository.list(q="Brand New Notion Book")

        assert client.calls == 1
        assert [book.title for book in results] == ["Brand New Notion Book"]
        created = results[0]
        assert created.authors == ["Notion Author"]
        assert created.cover_url == "https://images.example.test/new-book.jpg"
        assert created.status == "reading"
        assert created.page_count == 240
        assert created.current_page == 60
        assert created.source == "Notion"
        assert created.external_ids["notion_page_id"] == "new-book-page"
        assert created.metadata_state["notion_cover_url"] == (
            "https://images.example.test/new-book.jpg"
        )
        assert created.metadata_state["notion_progress_percent"] == 25


def test_book_notion_client_reads_cover_from_files_property():
    client = BookNotionSyncClient(token="token", data_source_id="source")
    client._schema_cache = {
        "Name": {"type": "title"},
        "Authors": {"type": "rich_text"},
        "cover": {"type": "files"},
    }

    item = client._page_to_book(
        {
            "id": "page-1",
            "url": "https://notion.example.test/page-1",
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"plain_text": "عبث الأقدار"}],
                },
                "Authors": {
                    "type": "rich_text",
                    "rich_text": [{"plain_text": "نجيب محفوظ"}],
                },
                "cover": {
                    "type": "files",
                    "files": [
                        {
                            "name": "cover.jpg",
                            "type": "external",
                            "external": {
                                "url": "https://images.example.test/abath-cover.jpg"
                            },
                        }
                    ],
                },
            },
        }
    )

    assert item["title"] == "عبث الأقدار"
    assert item["authors"] == ["نجيب محفوظ"]
    assert item["cover_url"] == "https://images.example.test/abath-cover.jpg"


def test_book_notion_schema_guard_rejects_movie_database_shape():
    assert _is_book_schema(
        {
            "Name": {"type": "title"},
            "Author": {"type": "multi_select"},
            "Pages": {"type": "number"},
            "Pages Read": {"type": "number"},
        }
    )
    assert not _is_book_schema(
        {
            "Name": {"type": "title"},
            "Media Type": {"type": "select"},
            "TMDB ID": {"type": "number"},
            "Director": {"type": "rich_text"},
            "Season": {"type": "number"},
            "Episode": {"type": "number"},
        }
    )


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


def test_article_projection_removes_chrome_and_labels_video_summaries():
    article = Article(
        title="A video report",
        url="https://example.test/video/newsfeed/report",
        content_text=(
            "A video report\n\n"
            "This is the useful source summary with enough context to remain readable.\n\n"
            "Save\n\nShare\n\nThis is the useful source summary with enough context "
            "to remain readable."
        ),
    )

    detail = article_detail(article)

    assert detail["content_label"] == "Video summary"
    assert detail["content_paragraphs"] == [
        "This is the useful source summary with enough context to remain readable."
    ]
    assert article_content_is_readable(article) is False
    media_article = Article(
        title="A media report",
        url="https://example.test/news/media",
        content_text="Short text",
        content_blocks=[
            {"kind": "text", "text": "Short text"},
            {"kind": "image", "src": "https://example.test/media.jpg"},
        ],
    )
    assert article_content_is_readable(media_article) is True
    assert article_paragraphs("الرئيسية\n\nسياسة\n\nرياضة", title="خبر") == [
        "الرئيسية",
        "سياسة",
        "رياضة",
    ]


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

        def fetch_durations(self, video_ids, *, maximum):
            assert video_ids == ["shared-video"]
            assert maximum == 5000
            return {"shared-video": 542}

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
        assert {row.duration_seconds for row in rows} == {542}


def test_pockettube_sync_uses_latest_video_from_each_exported_channel(app, tmp_path):
    export = tmp_path / "youtube_subscription_manager_2026-07-19-04_31.json"
    export.write_text(
        '{"tech":["UCchannel111111"],"news":["UCchannel222222"],"ysc_settings":{}}',
        encoding="utf-8",
    )

    class Client:
        def fetch_latest_channel_uploads(self, channel_ids, *, maximum):
            assert channel_ids == ["UCchannel111111", "UCchannel222222"]
            assert maximum == 10000
            return {
                "UCchannel111111": {
                    "id": "upload-1",
                    "snippet": {
                        "title": "Latest tech",
                        "resourceId": {"videoId": "video-tech"},
                        "channelTitle": "Tech Channel",
                        "publishedAt": "2026-07-19T00:00:00Z",
                    },
                },
                "UCchannel222222": {
                    "id": "upload-2",
                    "snippet": {
                        "title": "Latest news",
                        "resourceId": {"videoId": "video-news"},
                        "channelTitle": "News Channel",
                        "publishedAt": "2026-07-18T00:00:00Z",
                    },
                },
            }

        def fetch_durations(self, video_ids, *, maximum):
            assert video_ids == ["video-tech", "video-news"]
            return {"video-tech": 900, "video-news": 1200}

    with app.app_context():
        counts = YouTubeService.sync_pockettube(Client(), export)
        videos = db.session.scalars(
            db.select(YouTubeVideo).where(YouTubeVideo.source == "pockettube")
        ).all()

        assert counts["channels"] == 2
        assert counts["videos"] == 2
        assert [video.title for video in sorted(videos, key=lambda item: item.position)] == [
            "Latest tech",
            "Latest news",
        ]
        assert {video.group_name for video in videos} == {"tech", "news"}


def test_pockettube_sync_caps_each_group_at_200_videos(app, tmp_path):
    channels = [f"UCchannel{index:04d}" for index in range(205)]
    export = tmp_path / "youtube_subscription_manager_2026-07-19-04_31.json"
    export.write_text(json.dumps({"big": channels}), encoding="utf-8")

    class Client:
        def fetch_latest_channel_uploads(self, channel_ids, *, maximum):
            assert channel_ids == channels
            return {
                channel_id: {
                    "id": f"upload-{index}",
                    "snippet": {
                        "title": f"Latest video {index}",
                        "resourceId": {"videoId": f"video-{index}"},
                        "channelTitle": f"Channel {index}",
                        "publishedAt": f"2026-07-19T00:{index % 60:02d}:00Z",
                    },
                }
                for index, channel_id in enumerate(channels)
            }

        def fetch_durations(self, video_ids, *, maximum):
            return {}

    with app.app_context():
        counts = YouTubeService.sync_pockettube(Client(), export)
        feed = YouTubeService.feed(source="pockettube", group="big", limit=None)
        groups = YouTubeRepository.groups()

        assert counts["videos"] == 200
        assert feed["total"] == 200
        assert groups == [{"name": "big", "count": 200}]


def test_pockettube_sync_fills_small_groups_with_multiple_uploads(app, tmp_path):
    channels = [f"UCsmall{index:04d}" for index in range(4)]
    export = tmp_path / "youtube_subscription_manager_2026-07-19-04_31.json"
    export.write_text(json.dumps({"small": channels}), encoding="utf-8")

    class Client:
        def fetch_channel_uploads(self, channel_limits, *, maximum):
            assert channel_limits == {channel_id: 100 for channel_id in channels}
            return {
                channel_id: [
                    {
                        "id": f"upload-{channel_index}-{video_index}",
                        "snippet": {
                            "title": f"Video {channel_index}-{video_index}",
                            "resourceId": {
                                "videoId": f"video-{channel_index}-{video_index}"
                            },
                            "channelTitle": f"Channel {channel_index}",
                            "publishedAt": f"2026-07-19T{video_index % 24:02d}:00:00Z",
                        },
                    }
                    for video_index in range(100)
                ]
                for channel_index, channel_id in enumerate(channels)
            }

        def fetch_durations(self, video_ids, *, maximum):
            return {}

    with app.app_context():
        counts = YouTubeService.sync_pockettube(Client(), export)
        feed = YouTubeService.feed(source="pockettube", group="small", limit=None)

        assert counts["videos"] == 200
        assert feed["total"] == 200


def test_pockettube_sync_keeps_shared_channels_in_each_group(app, tmp_path):
    export = tmp_path / "youtube_subscription_manager_2026-07-19-04_31.json"
    export.write_text(
        json.dumps({"news": ["UCshared0001"], "my favoret": ["UCshared0001"]}),
        encoding="utf-8",
    )

    class Client:
        def fetch_channel_uploads(self, channel_limits, *, maximum):
            assert channel_limits == {"UCshared0001": 200}
            return {
                "UCshared0001": [
                    {
                        "id": f"upload-{index}",
                        "snippet": {
                            "title": f"Shared video {index}",
                            "resourceId": {"videoId": f"shared-video-{index}"},
                            "channelTitle": "Shared Channel",
                            "publishedAt": f"2026-07-19T00:{index % 60:02d}:00Z",
                        },
                    }
                    for index in range(200)
                ]
            }

        def fetch_durations(self, video_ids, *, maximum):
            return {}

    with app.app_context():
        counts = YouTubeService.sync_pockettube(Client(), export)
        news = YouTubeService.feed(source="pockettube", group="news", limit=None)
        favorite = YouTubeService.feed(source="pockettube", group="my favoret", limit=None)

        assert counts["videos"] == 400
        assert news["total"] == 200
        assert favorite["total"] == 200
        assert news["items"][0]["external_id"].startswith("shared-video-")


def test_pockettube_sync_preserves_cached_group_fill_when_api_underfills(app, tmp_path):
    export = tmp_path / "youtube_subscription_manager_2026-07-19-04_31.json"
    export.write_text(json.dumps({"news": ["UCnews0001"]}), encoding="utf-8")

    class Client:
        def fetch_channel_uploads(self, channel_limits, *, maximum):
            return {
                "UCnews0001": [
                    {
                        "id": "upload-new",
                        "snippet": {
                            "title": "New video",
                            "resourceId": {"videoId": "new-video"},
                            "channelTitle": "News",
                            "publishedAt": "2026-07-19T00:00:00Z",
                        },
                    }
                ]
            }

        def fetch_durations(self, video_ids, *, maximum):
            return {}

    with app.app_context():
        db.session.add_all(
            [
                YouTubeVideo(
                    external_id=f"cached-{index}",
                    source="pockettube",
                    group_name="news",
                    title=f"Cached {index}",
                    position=index,
                    removed_from_source=index >= 50,
                )
                for index in range(199)
            ]
        )
        db.session.commit()

        counts = YouTubeService.sync_pockettube(Client(), export)
        feed = YouTubeService.feed(source="pockettube", group="news", limit=None)

        assert counts["videos"] == 200
        assert feed["total"] == 200


def test_pockettube_sync_skips_shorts(app, tmp_path):
    export = tmp_path / "youtube_subscription_manager_2026-07-19-04_31.json"
    export.write_text(json.dumps({"news": ["UCnews0001"]}), encoding="utf-8")

    class Client:
        def fetch_channel_uploads(self, channel_limits, *, maximum):
            return {
                "UCnews0001": [
                    {
                        "id": "upload-short",
                        "snippet": {
                            "title": "Quick update #Shorts",
                            "resourceId": {"videoId": "short-video"},
                            "channelTitle": "News",
                            "publishedAt": "2026-07-19T00:00:00Z",
                        },
                    },
                    {
                        "id": "upload-long",
                        "snippet": {
                            "title": "Full report",
                            "resourceId": {"videoId": "long-video"},
                            "channelTitle": "News",
                            "publishedAt": "2026-07-19T01:00:00Z",
                        },
                    },
                ]
            }

        def fetch_durations(self, video_ids, *, maximum):
            return {"short-video": 42, "long-video": 540}

    with app.app_context():
        counts = YouTubeService.sync_pockettube(Client(), export)
        feed = YouTubeService.feed(source="pockettube", group="news", limit=None)

        assert counts["shorts_skipped"] == 1
        assert feed["total"] == 1
        assert feed["items"][0]["external_id"] == "long-video"


def test_pockettube_sync_does_not_refill_from_cached_shorts(app, tmp_path):
    export = tmp_path / "youtube_subscription_manager_2026-07-19-04_31.json"
    export.write_text(json.dumps({"news": ["UCnews0001"]}), encoding="utf-8")

    class Client:
        def fetch_channel_uploads(self, channel_limits, *, maximum):
            return {}

        def fetch_durations(self, video_ids, *, maximum):
            return {}

    with app.app_context():
        db.session.add_all(
            [
                YouTubeVideo(
                    external_id="cached-short",
                    source="pockettube",
                    group_name="news",
                    title="Cached short",
                    duration_seconds=45,
                ),
                YouTubeVideo(
                    external_id="cached-long",
                    source="pockettube",
                    group_name="news",
                    title="Cached long",
                    duration_seconds=600,
                ),
            ]
        )
        db.session.commit()

        YouTubeService.sync_pockettube(Client(), export)
        feed = YouTubeService.feed(source="pockettube", group="news", limit=None)

        assert feed["total"] == 1
        assert feed["items"][0]["external_id"] == "cached-long"


def test_pockettube_feed_hides_removed_cache_entries(app):
    with app.app_context():
        db.session.add_all(
            [
                YouTubeVideo(
                    external_id="fresh",
                    source="pockettube",
                    group_name="tech",
                    title="Fresh video",
                    removed_from_source=False,
                ),
                YouTubeVideo(
                    external_id="old",
                    source="pockettube",
                    group_name="tech",
                    title="Old cached video",
                    removed_from_source=True,
                ),
            ]
        )
        db.session.commit()

        feed = YouTubeService.feed(source="pockettube", group="tech")
        groups = YouTubeRepository.groups()

        assert feed["total"] == 1
        assert [item["title"] for item in feed["items"]] == ["Fresh video"]
        assert groups == [{"name": "tech", "count": 1}]


def test_pockettube_group_resolver_accepts_old_favorite_label(app):
    with app.app_context():
        db.session.add(
            YouTubeVideo(
                external_id="fresh",
                source="pockettube",
                group_name="my favoret",
                title="Fresh video",
            )
        )
        db.session.commit()

        assert YouTubeRepository.resolve_group("My Favorite") == "my favoret"
