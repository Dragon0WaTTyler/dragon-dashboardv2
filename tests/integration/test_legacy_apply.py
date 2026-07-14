import json
from pathlib import Path

from app.chess.models import ChessGame
from app.extensions import db
from app.migration.legacy import apply_legacy_import
from app.movies.models import Movie
from app.reading.models import Article, ReadingSource


def _write_json(path: Path, value):
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
    before = {path.name: path.read_bytes() for path in source.iterdir()}

    with app.app_context():
        first = apply_legacy_import(source, target)
        environment_after_first = (target / ".env").read_bytes()
        second = apply_legacy_import(source, target)

        assert db.session.query(Movie).count() == 1
        assert db.session.query(ReadingSource).count() == 1
        assert db.session.query(Article).count() == 1
        assert db.session.query(ChessGame).count() == 1
        assert first["counts"]["movies_created"] == 1
        assert second["counts"]["movies_updated"] == 1

    assert (target / ".env").read_bytes() == environment_after_first
    assert "private-test-value" in (target / ".env").read_text(encoding="utf-8")
    assert (target / "instance" / "secrets" / "client_secret.json").exists()
    assert "private-test-value" not in json.dumps(first)
    assert before == {path.name: path.read_bytes() for path in source.iterdir()}
