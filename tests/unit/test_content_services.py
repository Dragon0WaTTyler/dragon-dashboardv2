import json
from datetime import UTC, datetime, timedelta

import pytest

from app.books.models import Book
from app.books.services import BookService, book_item
from app.extensions import db
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
        db.session.add_all([*movies, *videos, *favorite_videos])
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
        assert len(first_video_ids) == len(next_video_ids) == 4
        assert len(first_favorite_ids) == len(next_favorite_ids) == 4
        assert first_video_ids.isdisjoint(next_video_ids)
        assert first_favorite_ids.isdisjoint(next_favorite_ids)
        assert first["rotation"]["movie_interval_seconds"] == 3600
        assert first["rotation"]["youtube_interval_seconds"] == 300


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
