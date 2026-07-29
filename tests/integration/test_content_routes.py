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
    assert f'data-article-open="/reading/{ids["article"]}/open"' in today_html


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
    assert f'data-article-open="/reading/{article_id}/open"' in html

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
