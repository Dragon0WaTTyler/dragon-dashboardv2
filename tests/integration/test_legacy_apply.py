import json
from pathlib import Path

from app.books.models import Book, Quote
from app.chess.models import ChessGame
from app.extensions import db
from app.migration.legacy import apply_legacy_import
from app.movies.models import Movie
from app.reading.models import Article, ReadingSource
from app.youtube.models import YouTubeVideo


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_legacy_apply_imports_supported_records_and_keeps_secrets_local(app, tmp_path):
    source = tmp_path / "legacy"
    target = tmp_path / "dragon"
    source.mkdir()
    target.mkdir()
    (source / ".env").write_text("TMDB_API_KEY=private-test-value\n", encoding="utf-8")
    (source / "client_secret.json").write_text('{"web":{"client_id":"private"}}')
    _write_json(
        source / "cache_data.json",
        {
            "films": {
                "all": {
                    "data": [
                        {
                            "name": "Heat",
                            "year": 1995,
                            "status": "Finished",
                            "notion_page_id": "legacy-movie-1",
                            "magnet_hd": "magnet:?xt=test",
                            "poster": "https://www.themoviedb.org/t/p/w600/poster.jpg",
                        }
                    ]
                }
            }
        },
    )
    _write_json(
        source / "reading_data.json",
        {
            "sources": [{"id": "feed-1", "name": "Journal", "url": "https://feed"}],
            "entries": [
                {
                    "id": "article-1",
                    "source_id": "feed-1",
                    "title": "A private read",
                    "url": "https://article",
                    "status": "unread",
                }
            ],
        },
    )
    _write_json(
        source / "chess_data.json",
        {
            "games": [
                {
                    "id": "game-1",
                    "source": "lichess",
                    "white": "White",
                    "black": "Black",
                    "result": "1-0",
                }
            ],
            "puzzle_seeds": [],
            "puzzle_attempts": [],
            "auto_puzzle_candidates": [],
        },
    )
    _write_json(source / "playlists.json", {})
    _write_json(source / "deleted_history.json", [])
    _write_json(
        source / "cache" / "books_snapshot.json",
        {
            "entries": [
                {
                    "id": "book-1",
                    "notion_page_id": "book-1",
                    "title": "Private book",
                    "authors": ["Author"],
                    "status": "read",
                    "cover_url": "https://www.themoviedb.org/t/p/w600/cover.jpg",
                }
            ]
        },
    )
    _write_json(
        source / "cache" / "quotes_snapshot.json",
        {
            "entries": [
                {
                    "id": "quote-1",
                    "notion_page_id": "quote-1",
                    "book_relation_ids": ["book-1"],
                    "quote": "A useful line.",
                }
            ]
        },
    )
    _write_json(
        source / "cache" / "youtube_latest_snapshot.json",
        {
            "groups": {
                "tech": {
                    "group_name": "Tech",
                    "videos": [
                        {
                            "video_id": "video-1",
                            "title": "A cached video",
                            "channel_id": "channel-1",
                            "channel_title": "Channel",
                            "thumbnail_url": "https://img.youtube.com/video-1.jpg",
                        }
                    ],
                }
            }
        },
    )
    _write_json(source / "youtube_duration_cache.json", {"video-1": {"seconds": 90}})
    before = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }

    with app.app_context():
        first = apply_legacy_import(source, target)
        environment_after_first = (target / ".env").read_bytes()
        second = apply_legacy_import(source, target)

        assert db.session.query(Movie).count() == 1
        assert db.session.query(ReadingSource).count() == 1
        assert db.session.query(Article).count() == 1
        assert db.session.query(ChessGame).count() == 1
        assert db.session.query(Book).count() == 1
        assert db.session.query(Quote).count() == 1
        assert db.session.query(YouTubeVideo).count() == 1
        assert db.session.scalar(db.select(Movie)).poster_url.endswith("/w500/poster.jpg")
        assert db.session.scalar(db.select(Book)).cover_url.endswith("/w500/cover.jpg")
        assert db.session.scalar(db.select(YouTubeVideo)).duration_seconds == 90
        assert first["counts"]["movies_created"] == 1
        assert first["counts"]["books_created"] == 1
        assert first["counts"]["quotes_created"] == 1
        assert first["counts"]["pockettube_created"] == 1
        assert second["counts"]["movies_updated"] == 1

    assert (target / ".env").read_bytes() == environment_after_first
    assert "private-test-value" in (target / ".env").read_text(encoding="utf-8")
    assert (target / "instance" / "secrets" / "client_secret.json").exists()
    assert (
        target / "instance" / "legacy-import" / "raw" / "cache" / "books_snapshot.json"
    ).exists()
    assert "private-test-value" not in json.dumps(first)
    assert before == {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
