from datetime import datetime, timedelta

from app.books.models import Book, Quote
from app.extensions import db
from app.movies.models import Movie, MovieProgress
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
            thumbnail_url="https://images.example.test/video.jpg",
            duration_seconds=754,
            description="A local summary.\n\n00:00 Opening\n02:30 Main lesson",
        )
        watch_video = YouTubeVideo(
            external_id="watch-seed",
            source="watch_later",
            channel_title="Saved Channel",
            title="A saved video",
            thumbnail_url="https://images.example.test/watch-video.jpg",
            duration_seconds=4112,
        )
        rtl_video = YouTubeVideo(
            external_id="rtl-seed",
            source="pockettube",
            group_name="Learning",
            channel_title="Arabic Channel",
            title="شرح عربي للفيديو",
            thumbnail_url="https://images.example.test/rtl-video.jpg",
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
            personal_score=4.5,
            favorite=True,
            collections=["Shelf Alpha", "Shelf Beta"],
            personal_notes="Keep this one close for the next reread.",
            cover_url="https://images.example.test/book.jpg",
        )
        book.quotes.append(
            Quote(text="A line worth keeping.", note="Pocket note", page=19)
        )
        movie = Movie(
            title="A Daily Film",
            normalized_title="a daily film",
            status="want_to_watch",
            poster_url="https://images.example.test/movie.jpg",
        )
        series = Movie(
            title="Active Series",
            normalized_title="active series",
            status="watching",
            media_type="tv",
            poster_url="https://images.example.test/series.jpg",
        )
        db.session.add_all([video, watch_video, rtl_video, source, article, book, movie, series])
        db.session.flush()
        db.session.add(
            MovieProgress(
                movie_id=series.id,
                season=1,
                episode=5,
                current_seconds=2400,
                duration_seconds=2400,
                completed=True,
            )
        )
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

    book_detail = authenticated_client.get(f"/books/{ids['book']}").get_data(as_text=True)
    assert 'class="book-detail' in book_detail
    assert 'src="https://images.example.test/book.jpg"' in book_detail
    assert "Reading context" in book_detail
    assert "Current copies" in book_detail
    assert "Register a file" in book_detail
    assert "Track an edition" in book_detail
    assert "Synced lines" in book_detail
    assert "Saved lines" in book_detail
    assert "Capture" in book_detail
    assert "Shelf Alpha, Shelf Beta" in book_detail
    assert "Keep this one close for the next reread." in book_detail
    books_index = authenticated_client.get("/books").get_data(as_text=True)
    assert "Search library" in books_index
    assert "Search titles, authors, and shelves." in books_index
    assert "Diagnostics" in books_index
    assert "Edition &amp; audio" not in books_index
    assert "Browse the library by maintenance lane" not in books_index
    diagnostics = authenticated_client.get("/settings/knowledge/diagnostics").get_data(
        as_text=True
    )
    assert "Browse cleanup lanes from diagnostics" in diagnostics
    assert "Formats" in diagnostics

    youtube_detail = authenticated_client.get(f"/youtube/{ids['video']}")
    youtube_html = youtube_detail.get_data(as_text=True)
    assert "data-player-launch" in youtube_html
    assert 'data-video-id="yt-seed"' in youtube_html
    assert 'data-youtube-start="150"' in youtube_html
    assert "About this video" in youtube_html
    assert "Continue watching" in youtube_html
    assert "mode=youtube_study" in youtube_html
    assert "context_type=youtube" in youtube_html
    policy = youtube_detail.headers["Content-Security-Policy"]
    assert "frame-src 'self' https://www.youtube-nocookie.com https://www.youtube.com" in policy
    assert "script-src 'self' https://www.youtube.com" in policy


def test_library_viewers_and_thumbnails_render(authenticated_client, app):
    ids = seed_content(app)
    grid = authenticated_client.get("/books?view=grid")
    compact = authenticated_client.get("/books?view=list")
    invalid = authenticated_client.get("/books?view=unknown")
    reading_grid = authenticated_client.get("/reading?view=grid")
    reading_list = authenticated_client.get("/reading?view=list")
    reading_invalid = authenticated_client.get("/reading?view=unknown")
    youtube_grid = authenticated_client.get("/youtube?source=pockettube&view=grid")
    youtube_list = authenticated_client.get("/youtube?source=pockettube&view=list")
    youtube_invalid = authenticated_client.get(
        "/youtube?source=pockettube&view=unknown"
    )
    today = authenticated_client.get("/")

    assert 'class="book-grid"' in grid.get_data(as_text=True)
    assert "book-grid--list" in compact.get_data(as_text=True)
    assert "book-grid--list" not in invalid.get_data(as_text=True)
    assert "article-list--grid" in reading_grid.get_data(as_text=True)
    assert "article-list--grid" not in reading_list.get_data(as_text=True)
    assert "article-card--rtl" in reading_list.get_data(as_text=True)
    assert "article-list--grid" in reading_invalid.get_data(as_text=True)
    assert "media-list--grid" in youtube_grid.get_data(as_text=True)
    assert "media-list--grid" not in youtube_list.get_data(as_text=True)
    assert "media-row--rtl" in youtube_list.get_data(as_text=True)
    assert "media-list--grid" in youtube_invalid.get_data(as_text=True)
    assert 'class="media-duration" aria-label="Duration 12:34">12:34</span>' in (
        youtube_grid.get_data(as_text=True)
    )
    reading_html = reading_grid.get_data(as_text=True)
    assert 'src="https://images.example.test/article.jpg"' in reading_html
    assert 'dir="auto"' in reading_html
    today_html = today.get_data(as_text=True)
    assert "focus-strip" not in today_html
    assert "Choose one thing" not in today_html
    assert "Pick up where you stopped" not in today_html
    assert "season=1&amp;episode=6#movie-player" in today_html
    assert 'class="today-feature"' in today_html
    assert 'src="https://images.example.test/movie.jpg"' in today_html
    assert 'src="https://images.example.test/watch-video.jpg"' in today_html
    assert "1:08:32" in today_html
    assert 'src="https://images.example.test/article.jpg"' in today_html
    assert 'src="https://images.example.test/book.jpg"' in today_html
    assert f'data-article-open="/reading/{ids["article"]}/open?return_to=' in today_html


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

    first = authenticated_client.get(
        "/youtube?source=watch_later&view=list&per_page=50"
    )
    second = authenticated_client.get("/youtube?source=watch_later&per_page=50&page=2")
    shuffled = authenticated_client.get(
        "/youtube?source=watch_later&order=shuffle&seed=stable-seed&per_page=50"
    )

    assert ">Next</a>" in first.get_data(as_text=True)
    assert "view=list" in first.get_data(as_text=True)
    assert "Watch video 50" in second.get_data(as_text=True)
    assert ">Previous</a>" in second.get_data(as_text=True)
    assert "seed=stable-seed" in shuffled.get_data(as_text=True)


def test_youtube_detail_preserves_the_collection_return_context(authenticated_client, app):
    ids = seed_content(app)
    default_index = authenticated_client.get("/youtube?source=watch_later")
    index = authenticated_client.get(
        "/youtube?source=pockettube&group=Learning&q=focused&order=shuffle&seed=stable"
    )
    html = index.get_data(as_text=True)

    default_html = default_index.get_data(as_text=True)
    assert "Shuffle order" in default_html
    assert "Compact list" in default_html
    assert "youtube-filter-details" not in default_html
    assert f"/youtube/{ids['video']}?return_to=" in html
    assert "group%3DLearning" in html
    assert "seed%3Dstable" in html


def test_youtube_connect_uses_the_running_app_callback(
    authenticated_client, app
):
    class Client:
        @staticmethod
        def authorization_url(redirect_uri, state):
            assert redirect_uri == "http://localhost/youtube/oauth/callback"
            assert state
            return "https://accounts.google.com/o/oauth2/v2/auth?state=test"

    with app.app_context():
        app.extensions["dragon_youtube_playlist_client"] = Client()

    response = authenticated_client.get("/youtube/connect", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].startswith("https://accounts.google.com/")


def test_youtube_delete_requires_confirmation_and_then_removes_from_youtube(
    authenticated_client, app
):
    class Client:
        deleted_playlist_item_id = ""

        def delete_playlist_item(self, playlist_item_id):
            self.deleted_playlist_item_id = playlist_item_id

    with app.app_context():
        video = YouTubeVideo(
            external_id="delete-video",
            playlist_item_id="playlist-item-delete",
            source="watch_later",
            title="Delete me",
        )
        db.session.add(video)
        db.session.commit()
        video_id = video.id
        app.extensions["dragon_youtube_playlist_client"] = Client()
        app.config["DRAGON_YOUTUBE_DELETE_ENABLED"] = True

    page = authenticated_client.get(f"/youtube/{video_id}")
    no_confirmation = authenticated_client.post(
        f"/youtube/{video_id}/remove",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=False,
    )
    assert no_confirmation.status_code == 302
    with app.app_context():
        assert db.session.get(YouTubeVideo, video_id).removed_from_source is False

    confirmed = authenticated_client.post(
        f"/youtube/{video_id}/remove",
        data={"csrf_token": csrf_from(page), "confirmed": "yes", "return_to": "/youtube"},
        follow_redirects=False,
    )
    assert confirmed.headers["Location"].endswith("/youtube")
    with app.app_context():
        assert app.extensions["dragon_youtube_playlist_client"].deleted_playlist_item_id == (
            "playlist-item-delete"
        )
        assert db.session.get(YouTubeVideo, video_id).removed_from_source is True


def test_fulltext_status_get_is_read_only(authenticated_client, app):
    article_id = seed_content(app)["article"]
    with app.app_context():
        before = db.session.get(Article, article_id).updated_at
    response = authenticated_client.get(f"/reading/{article_id}/fulltext-status")
    assert response.status_code == 200
    assert response.get_json()["state"] == "not_requested"
    with app.app_context():
        assert db.session.get(Article, article_id).updated_at == before


def test_article_open_post_is_safe_when_extractor_unavailable(
    authenticated_client, app
):
    article_id = seed_content(app)["article"]
    page = authenticated_client.get(f"/reading/{article_id}")
    response = authenticated_client.post(
        f"/reading/{article_id}/open",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )
    assert "full article is unavailable" in response.get_data(as_text=True)
    with app.app_context():
        article = db.session.get(Article, article_id)
        assert article.fulltext_state == "not_requested"
        assert article.content_text == ""


def test_article_click_loads_and_caches_full_text(authenticated_client, app):
    class Extractor:
        @staticmethod
        def extract(url):
            assert url == "https://example.test/article"
            return {
                "content_text": (
                    "This complete article is loaded only after the reader chooses it. "
                    "The cached copy is then used on every later detail request."
                )
            }

    article_id = seed_content(app)["article"]
    app.extensions["dragon_article_extractor"] = Extractor()
    page = authenticated_client.get("/reading?view=list")
    html = page.get_data(as_text=True)
    assert f'data-article-open="/reading/{article_id}/open?return_to=' in html

    response = authenticated_client.post(
        f"/reading/{article_id}/open",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )
    detail_html = response.get_data(as_text=True)
    assert "This complete article is loaded only" in detail_html
    assert "Load full article explicitly" not in detail_html
    assert "Full-text cache" not in detail_html
    with app.app_context():
        article = db.session.get(Article, article_id)
        assert article.fulltext_state == "cached"
        assert article.status == "reading"


def test_article_refresh_replaces_a_bad_cached_copy(authenticated_client, app):
    class Extractor:
        @staticmethod
        def extract(url):
            assert url == "https://example.test/article"
            return {
                "content_text": (
                    "The refreshed article now contains a complete, readable paragraph from "
                    "the original source instead of navigation labels."
                )
            }

    article_id = seed_content(app)["article"]
    with app.app_context():
        article = db.session.get(Article, article_id)
        article.content_text = "Home\n\nPolitics\n\nSport"
        article.fulltext_state = "cached"
        db.session.commit()
    app.extensions["dragon_article_extractor"] = Extractor()
    page = authenticated_client.get(f"/reading/{article_id}")

    response = authenticated_client.post(
        f"/reading/{article_id}/refresh",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "The refreshed article now contains" in html
    assert "Article text refreshed" in html
    assert "Refresh text" in html


def test_article_detail_get_never_calls_extractor(authenticated_client, app):
    class Extractor:
        @staticmethod
        def extract(url):
            raise AssertionError(f"GET unexpectedly extracted {url}")

    article_id = seed_content(app)["article"]
    app.extensions["dragon_article_extractor"] = Extractor()
    response = authenticated_client.get(f"/reading/{article_id}")
    assert response.status_code == 200
    assert "Stored locally." in response.get_data(as_text=True)


def test_news_feeds_saved_state_pagination_and_return_context(authenticated_client, app):
    now = datetime.now().astimezone()
    with app.app_context():
        source = ReadingSource(name="News feed", feed_url="https://example.test/news")
        today = Article(
            source=source,
            title="Today article",
            url="https://example.test/today",
            published_at=now,
        )
        older = Article(
            source=source,
            title="Older article",
            url="https://example.test/older",
            published_at=now - timedelta(days=2),
        )
        saved = Article(
            source=source,
            title="Saved while reading",
            url="https://example.test/saved",
            status="reading",
            is_saved=True,
            published_at=now - timedelta(days=1),
        )
        page_two = [
            Article(
                source=source,
                title=f"Paged article {index}",
                url=f"https://example.test/paged-{index}",
                published_at=now - timedelta(minutes=index),
            )
            for index in range(21)
        ]
        db.session.add_all([source, today, older, saved, *page_two])
        db.session.commit()
        saved_id = saved.id

    today_page = authenticated_client.get("/reading?feed=today")
    today_html = today_page.get_data(as_text=True)
    assert "Today article" in today_html
    assert "Older article" not in today_html
    assert 'aria-current="page">Today</a>' in today_html

    recent_html = authenticated_client.get("/reading?feed=recent").get_data(as_text=True)
    assert "Today article" in recent_html

    saved_html = authenticated_client.get("/reading?feed=saved&status=reading").get_data(
        as_text=True
    )
    assert "Saved while reading" in saved_html
    assert "Older article" not in saved_html
    assert "Save for later" not in saved_html

    first_page = authenticated_client.get("/reading?feed=recent").get_data(as_text=True)
    assert "Showing 1–20 of 24" in first_page
    assert ">Next</a>" in first_page
    second_page = authenticated_client.get("/reading?feed=recent&page=2").get_data(as_text=True)
    assert "Paged article 20" in second_page
    assert "Older article" in second_page
    assert ">Previous</a>" in second_page

    detail = authenticated_client.get(
        f"/reading/{saved_id}?return_to=/reading?feed=recent&view=list"
    )
    toggled = authenticated_client.post(
        f"/reading/{saved_id}/saved",
        data={
            "csrf_token": csrf_from(detail),
            "saved": "false",
            "return_to": "/reading?feed=recent&view=list",
        },
        follow_redirects=False,
    )
    assert "return_to=/reading?feed%3Drecent%26view%3Dlist" in toggled.headers["Location"]
    with app.app_context():
        article = db.session.get(Article, saved_id)
        assert article.is_saved is False
        assert article.status == "reading"


def test_news_empty_states_distinguish_filters_from_first_setup(authenticated_client, app):
    filtered = authenticated_client.get("/reading?feed=recent&q=no-match")
    filtered_html = filtered.get_data(as_text=True)
    assert "No articles match these filters" in filtered_html
    assert "Clear filters" in filtered_html
    assert "Manage sources" not in filtered_html

    empty = authenticated_client.get("/reading?feed=recent")
    empty_html = empty.get_data(as_text=True)
    assert "No cached articles yet" in empty_html
    assert "Manage sources" in empty_html


def test_reading_sync_button_fetches_current_feed_entries(authenticated_client, app):
    class Client:
        @staticmethod
        def fetch(url):
            return {
                "entries": [
                    {
                        "external_id": "latest-entry",
                        "title": "Latest article from sync",
                        "url": "https://example.test/latest",
                        "excerpt": "Newly synchronized.",
                    }
                ]
            }

    seed_content(app)
    app.extensions["dragon_feed_client"] = Client()
    page = authenticated_client.get("/reading")
    html = page.get_data(as_text=True)
    assert "Sync articles" in html
    assert 'data-reading-sync' in html

    response = authenticated_client.post(
        "/reading/sync",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )

    result_html = response.get_data(as_text=True)
    assert "Articles synced: 1 new, 0 updated." in result_html
    assert "Latest article from sync" in result_html
