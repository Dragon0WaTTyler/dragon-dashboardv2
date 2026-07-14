from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select

from app.books.models import Book, Quote
from app.chess.models import ChessCourse, ChessGame, ChessPuzzle, PuzzleAttempt
from app.extensions import db
from app.german.models import GermanResource
from app.history.models import HistoryEvent
from app.movies.models import Movie
from app.playback.models import PlaybackSource
from app.reading.models import Article, ReadingSource
from app.shared.models import LegacyIdMap
from app.shared.time import utc_iso, utc_now
from app.youtube.models import YouTubeVideo

RAW_FILES = (
    "admin_data.json",
    "cache_data.json",
    "chess_data.json",
    "reading_data.json",
    "deleted_history.json",
    "playlists.json",
    "youtube_duration_cache.json",
    "chat_history.db",
    "cache/books_snapshot.json",
    "cache/quotes_snapshot.json",
    "cache/youtube_latest_snapshot.json",
    "cache/youtube_latest_sync_status.json",
    "domains/youtube/data/pockettube_registry.json",
)
SECRET_FILES = ("client_secret.json", "youtube_token.json")
LEGACY_YOUTUBE_SETTING = re.compile(
    r"(?m)^\s*(API_KEY|PLAYLIST_ID)\s*=\s*['\"]([^'\"]+)['\"]\s*(?:#.*)?$"
)


def _json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _text(value: Any, *, limit: int | None = None) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("name") or value.get("username") or value.get("title") or ""
    result = str(value).strip()
    return result[:limit] if limit else result


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    for candidate in (normalized, normalized.replace(".", "-")):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.replace(tzinfo=parsed.tzinfo or UTC)
        except ValueError:
            continue
    return None


def _named_items(value: Any) -> list[dict[str, str]]:
    if isinstance(value, str):
        values = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, list):
        values = value
    elif value:
        values = [value]
    else:
        values = []
    result: list[dict[str, str]] = []
    for item in values:
        name = _text(item, limit=240)
        if name:
            result.append({"name": name})
    return result


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [part.strip() for part in value.split(",")]
    elif isinstance(value, list):
        values = value
    elif value:
        values = [value]
    else:
        values = []
    return [text for item in values if (text := _text(item, limit=500))]


def _normalize_poster_url(value: Any) -> str:
    url = _text(value, limit=1000)
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.netloc.lower() in {"www.themoviedb.org", "media.themoviedb.org"}:
        filename = Path(parsed.path).name
        if filename:
            return f"https://image.tmdb.org/t/p/w500/{filename}"
    return url


def _checksum(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def _remember(entity_type: str, source_id: str, target_id: str, source: Any) -> None:
    source_id = source_id[:255]
    row = db.session.scalar(
        select(LegacyIdMap).where(
            LegacyIdMap.source_system == "FlaskDashboard",
            LegacyIdMap.entity_type == entity_type,
            LegacyIdMap.source_id == source_id,
        )
    )
    if row is None:
        db.session.add(
            LegacyIdMap(
                source_system="FlaskDashboard",
                entity_type=entity_type,
                source_id=source_id,
                target_id=target_id,
                source_checksum=_checksum(source),
            )
        )
    else:
        row.target_id = target_id
        row.source_checksum = _checksum(source)
        row.imported_at = utc_now()


def _merge_dotenv(source: Path, target: Path) -> int:
    if not source.exists():
        return 0

    def keyed(lines: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for raw in lines:
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                result[line.split("=", 1)[0].strip()] = raw
        return result

    source_lines = source.read_text(encoding="utf-8-sig").splitlines()
    target_lines = target.read_text(encoding="utf-8-sig").splitlines() if target.exists() else []
    source_entries = keyed(source_lines)
    target_entries = keyed(target_lines)
    merged = list(target_lines)
    positions = {
        line.split("=", 1)[0].strip(): index
        for index, line in enumerate(merged)
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }
    new_source_keys = [key for key in source_entries if key not in positions]
    if new_source_keys and "# Legacy integrations migrated from FlaskDashboard" not in merged:
        merged.extend(["", "# Legacy integrations migrated from FlaskDashboard"])
    for key, raw in source_entries.items():
        if key in positions:
            merged[positions[key]] = raw
        else:
            merged.append(raw)
    defaults = {
        "DRAGON_ENV": "development",
        "DRAGON_AUTH_REQUIRED": "true",
        "DRAGON_PLAYBACK_ENABLED": "true",
        "DRAGON_MAGNETS_ENABLED": "true",
    }
    present = {**target_entries, **source_entries}
    new_default_keys = [key for key in defaults if key not in present]
    if new_default_keys and "# DragonV2 local runtime" not in merged:
        merged.extend(["", "# DragonV2 local runtime"])
    for key, value in defaults.items():
        if key not in present:
            merged.append(f"{key}={value}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(merged).rstrip() + "\n", encoding="utf-8")
    return len(source_entries)


def _copy_private_files(source: Path, project_root: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    raw_root = project_root / "instance" / "legacy-import" / "raw"
    secret_root = project_root / "instance" / "secrets"
    raw_root.mkdir(parents=True, exist_ok=True)
    secret_root.mkdir(parents=True, exist_ok=True)
    for name in RAW_FILES:
        source_path = source / name
        if source_path.exists():
            target_path = raw_root / name
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            counts["raw_files_archived"] += 1
    for name in SECRET_FILES:
        source_path = source / name
        if source_path.exists():
            shutil.copy2(source_path, secret_root / name)
            counts["secret_files_copied"] += 1
    legacy_playlist_script = source / "check_playlist.py"
    if legacy_playlist_script.exists():
        values = {
            name: value.strip()
            for name, value in LEGACY_YOUTUBE_SETTING.findall(
                legacy_playlist_script.read_text(encoding="utf-8-sig")
            )
        }
        for source_name, target_name in (
            ("API_KEY", "youtube_api_key"),
            ("PLAYLIST_ID", "youtube_watch_later_playlist_id"),
        ):
            value = values.get(source_name, "")
            if value:
                (secret_root / target_name).write_text(value, encoding="utf-8")
                counts["youtube_settings_copied"] += 1
    counts["environment_keys_migrated"] = _merge_dotenv(source / ".env", project_root / ".env")
    return counts


def _movie_status(value: Any) -> str:
    return {
        "i want to": "want_to_watch",
        "finished": "finished",
        "not finished": "watching",
        "watching": "watching",
    }.get(_text(value).lower(), "unknown")


def _import_movies(source: Path, counts: Counter[str]) -> None:
    cache = _json(source / "cache_data.json", {})
    records = cache.get("films", {}).get("all", {}).get("data", [])
    for record in records if isinstance(records, list) else []:
        title = _text(record.get("name"), limit=300)
        if not title:
            counts["movies_skipped"] += 1
            continue
        normalized = " ".join(title.casefold().split())
        year = _integer(record.get("year")) or None
        movie = db.session.scalar(
            select(Movie).where(Movie.normalized_title == normalized, Movie.year == year)
        )
        created = movie is None
        if movie is None:
            movie = Movie(title=title, normalized_title=normalized, year=year)
            db.session.add(movie)
            db.session.flush()
        movie.title = title
        movie.status = _movie_status(record.get("status"))
        movie.personal_score = _float(record.get("score_num") or record.get("score"))
        movie.category = _text(record.get("category"), limit=120)
        movie.source = _text(record.get("source"), limit=80) or "legacy"
        movie.overview = _text(record.get("overview"))
        movie.poster_url = _normalize_poster_url(record.get("poster"))
        movie.trailer_url = _text(record.get("trailer"), limit=1000)
        movie.runtime_minutes = _integer(record.get("runtime")) or None
        movie.genres = _named_items(record.get("genre_entries") or record.get("genres"))
        movie.directors = _named_items(record.get("director_entries") or record.get("director"))
        movie.external_ids = {"notion_page_id": _text(record.get("notion_page_id"))}
        movie.metadata_state = {
            "legacy_source": _text(record.get("source")),
            "tmdb_rating": _float(record.get("tmdb_rating")),
        }
        movie.watch_history = [
            item
            for item in (
                {"event": "watched", "at": _text(record.get("watch_date"))},
                {"event": "finished", "at": _text(record.get("finish_date"))},
            )
            if item["at"]
        ]
        for key, kind, label in (
            ("magnet_fhd", "magnet", "FHD magnet"),
            ("magnet_hd", "magnet", "HD magnet"),
            ("torrent_fhd", "torrent", "FHD torrent"),
            ("torrent_hd", "torrent", "HD torrent"),
            ("Magnet FHD", "magnet", "FHD magnet"),
            ("Magnet HD", "magnet", "HD magnet"),
            ("Torrent FHD", "torrent", "FHD torrent"),
            ("Torrent HD", "torrent", "HD torrent"),
        ):
            locator = _text(record.get(key))
            if not locator:
                continue
            existing = db.session.scalar(
                select(PlaybackSource).where(
                    PlaybackSource.movie_id == movie.id,
                    PlaybackSource.kind == kind,
                    PlaybackSource.locator == locator,
                )
            )
            if existing is None:
                db.session.add(
                    PlaybackSource(
                        movie_id=movie.id,
                        kind=kind,
                        label=label,
                        locator=locator,
                        metadata_json={"origin": "FlaskDashboard"},
                    )
                )
                counts["playback_sources_created"] += 1
        source_id = _text(record.get("notion_page_id")) or f"{normalized}:{year or ''}"
        _remember("movie", source_id, movie.id, record)
        counts["movies_created" if created else "movies_updated"] += 1


def _import_reading(source: Path, counts: Counter[str]) -> None:
    payload = _json(source / "reading_data.json", {})
    source_map: dict[str, str] = {}
    for record in payload.get("sources", []):
        feed_url = _text(
            record.get("url")
            or record.get("primary_url")
            or record.get("verified_url")
            or record.get("successful_url"),
            limit=1000,
        )
        if not feed_url:
            counts["reading_sources_skipped"] += 1
            continue
        item = db.session.scalar(select(ReadingSource).where(ReadingSource.feed_url == feed_url))
        created = item is None
        if item is None:
            item = ReadingSource(name=_text(record.get("name"), limit=240), feed_url=feed_url)
            db.session.add(item)
            db.session.flush()
        item.name = _text(record.get("name"), limit=240) or feed_url
        item.category = _text(record.get("category") or record.get("topic"), limit=120)
        item.active = bool(record.get("active", True))
        item.health_state = _text(record.get("status"), limit=30) or "unknown"
        item.health_message = _text(
            record.get("last_sync_message") or record.get("last_sync_error"), limit=500
        )
        item.last_success_at = _datetime(record.get("last_synced_at"))
        legacy_id = _text(record.get("id")) or feed_url
        source_map[legacy_id] = item.id
        source_map[feed_url] = item.id
        _remember("reading_source", legacy_id, item.id, record)
        counts["reading_sources_created" if created else "reading_sources_updated"] += 1

    for record in payload.get("entries", []):
        url = _text(record.get("canonical_url") or record.get("url"), limit=1500)
        title = _text(record.get("title"), limit=600)
        if not url or not title:
            counts["articles_skipped"] += 1
            continue
        external_id = _text(record.get("external_id") or record.get("id"), limit=500) or url
        item = db.session.scalar(
            select(Article).where((Article.external_id == external_id) | (Article.url == url))
        )
        created = item is None
        if item is None:
            item = Article(external_id=external_id, title=title, url=url)
            db.session.add(item)
            db.session.flush()
        source_key = _text(record.get("source_id") or record.get("feed_url"))
        item.source_id = source_map.get(source_key)
        item.title = title
        item.author = _text(record.get("author"), limit=240)
        item.topic = _text(record.get("topic") or record.get("category"), limit=160)
        item.excerpt = _text(record.get("excerpt") or record.get("summary"))
        item.content_text = _text(record.get("content_text"))
        item.image_url = _text(
            record.get("lead_image_url") or record.get("image_url"), limit=1000
        )
        item.status = _text(record.get("status"), limit=30) or "unread"
        item.fulltext_state = _text(record.get("extraction_status"), limit=30) or "not_requested"
        item.fulltext_error = _text(record.get("extraction_error"), limit=500)
        item.published_at = _datetime(record.get("published_at"))
        item.history = [{"event": "legacy_import", "at": utc_iso()}]
        _remember("article", external_id, item.id, record)
        counts["articles_created" if created else "articles_updated"] += 1


def _book_status(value: Any) -> str:
    return {
        "want to read": "want_to_read",
        "read": "finished",
        "not finished": "paused",
        "reading": "reading",
    }.get(_text(value).casefold(), "want_to_read")


def _mapped_entity(entity_type: str, source_id: str, model):
    mapping = db.session.scalar(
        select(LegacyIdMap).where(
            LegacyIdMap.source_system == "FlaskDashboard",
            LegacyIdMap.entity_type == entity_type,
            LegacyIdMap.source_id == source_id[:255],
        )
    )
    return db.session.get(model, mapping.target_id) if mapping else None


def _import_books(source: Path, counts: Counter[str]) -> None:
    books_payload = _json(source / "cache" / "books_snapshot.json", {})
    quotes_payload = _json(source / "cache" / "quotes_snapshot.json", {})
    book_by_source: dict[str, Book] = {}
    for record in books_payload.get("entries", []):
        title = _text(record.get("title"), limit=500)
        source_id = _text(record.get("notion_page_id") or record.get("id"), limit=255)
        if not title or not source_id:
            counts["books_skipped"] += 1
            continue
        normalized = " ".join(title.casefold().split())
        book = _mapped_entity("book", source_id, Book)
        if book is None:
            book = db.session.scalar(select(Book).where(Book.normalized_title == normalized))
        created = book is None
        if book is None:
            book = Book(title=title, normalized_title=normalized)
            db.session.add(book)
            db.session.flush()
        book.title = title
        book.normalized_title = normalized
        book.authors = _string_list(record.get("authors") or record.get("authors_display"))
        book.description = _text(
            record.get("content") or record.get("excerpt") or record.get("history")
        )
        book.cover_url = _normalize_poster_url(record.get("cover_url"))
        book.status = _book_status(record.get("status"))
        book.personal_score = _float(record.get("rating"))
        book.source = "notion_legacy_snapshot"
        book.external_ids = {"notion_page_id": source_id}
        book.metadata_state = {
            "tags": _string_list(record.get("tags")),
            "decision": _text(record.get("decision"), limit=240),
            "kind": _text(record.get("kinde"), limit=120),
            "pinned": bool(record.get("pinned")),
            "date_finished": _text(record.get("date_finished"), limit=80),
        }
        history_items = _string_list(
            record.get("history_paragraphs") or record.get("history")
        )
        book.history = [{"event": "legacy_note", "text": item} for item in history_items]
        book_by_source[source_id] = book
        book_by_source[_text(record.get("id"), limit=255)] = book
        _remember("book", source_id, book.id, record)
        counts["books_created" if created else "books_updated"] += 1

    for record in quotes_payload.get("entries", []):
        source_id = _text(record.get("notion_page_id") or record.get("id"), limit=255)
        quote_text = _text(record.get("quote"))
        relations = _string_list(
            record.get("book_relation_ids") or record.get("book_page_id")
        )
        book = next((book_by_source.get(relation) for relation in relations if relation), None)
        if not source_id or not quote_text or book is None:
            counts["quotes_skipped"] += 1
            continue
        quote = _mapped_entity("quote", source_id, Quote)
        created = quote is None
        if quote is None:
            quote = Quote(book_id=book.id, text=quote_text)
            db.session.add(quote)
            db.session.flush()
        quote.book_id = book.id
        quote.text = quote_text
        quote.page = _integer(record.get("page")) or None
        quote.note = _text(record.get("chapter"))
        _remember("quote", source_id, quote.id, record)
        counts["quotes_created" if created else "quotes_updated"] += 1


def _import_pockettube(source: Path, counts: Counter[str]) -> None:
    payload = _json(source / "cache" / "youtube_latest_snapshot.json", {})
    durations = _json(source / "youtube_duration_cache.json", {})
    seen: set[str] = set()
    position = 0
    for group_key, group in sorted(payload.get("groups", {}).items()):
        group_name = _text(group.get("group_name") or group_key, limit=160)
        for record in group.get("videos", []):
            external_id = _text(record.get("video_id"), limit=80)
            title = _text(record.get("title"), limit=500)
            if not external_id or not title:
                counts["pockettube_skipped"] += 1
                continue
            if external_id in seen:
                counts["pockettube_duplicates"] += 1
                continue
            seen.add(external_id)
            item = db.session.scalar(
                select(YouTubeVideo).where(
                    YouTubeVideo.source == "pockettube",
                    YouTubeVideo.external_id == external_id,
                )
            )
            created = item is None
            if item is None:
                item = YouTubeVideo(external_id=external_id, source="pockettube", title=title)
                db.session.add(item)
                db.session.flush()
            duration = durations.get(external_id, {})
            item.source = "pockettube"
            item.group_name = group_name
            item.channel_id = _text(record.get("channel_id"), limit=100)
            item.channel_title = _text(
                record.get("channel_title") or record.get("channel_name"), limit=240
            )
            item.title = title
            item.thumbnail_url = _text(
                record.get("thumbnail_url")
                or record.get("thumbnail")
                or record.get("image_url"),
                limit=1000,
            )
            item.published_at = _datetime(record.get("published_at"))
            item.duration_seconds = _integer(
                duration.get("seconds") if isinstance(duration, dict) else 0
            )
            item.position = position
            item.local_history = [
                {
                    "event": "legacy_snapshot_import",
                    "group_names": _string_list(record.get("group_names")),
                }
            ]
            position += 1
            _remember("youtube_video", external_id, item.id, record)
            counts["pockettube_created" if created else "pockettube_updated"] += 1


def _participant(value: Any) -> str:
    return _text(value, limit=180) or "Unknown"


def _import_chess(source: Path, counts: Counter[str]) -> None:
    payload = _json(source / "chess_data.json", {})
    for record in payload.get("games", []):
        external_id = _text(record.get("source_game_id") or record.get("id"), limit=120)
        if not external_id:
            counts["chess_games_skipped"] += 1
            continue
        game = db.session.scalar(select(ChessGame).where(ChessGame.external_id == external_id))
        created = game is None
        if game is None:
            game = ChessGame(
                external_id=external_id,
                source=_text(record.get("source"), limit=30) or "legacy",
                white=_participant(record.get("white")),
                black=_participant(record.get("black")),
            )
            db.session.add(game)
            db.session.flush()
        game.source = _text(record.get("source"), limit=30) or "legacy"
        game.white = _participant(record.get("white"))
        game.black = _participant(record.get("black"))
        game.user_color = _text(record.get("user_color"), limit=20) or "unknown"
        game.user_result = _text(record.get("user_result"), limit=20) or "unknown"
        game.result = _text(record.get("result"), limit=20) or "*"
        game.played_at = _datetime(record.get("end_time") or record.get("date"))
        game.time_class = _text(record.get("time_class"), limit=40) or "other"
        game.time_control = _text(record.get("time_control"), limit=60)
        opening = record.get("opening")
        game.opening = opening if isinstance(opening, dict) else {"name": _text(opening)}
        game.pgn = _text(record.get("pgn"))
        game.moves = [str(move) for move in record.get("moves", [])]
        game.source_url = _text(record.get("url"), limit=1000)
        game.rated = bool(record.get("rated", False))
        _remember("chess_game", external_id, game.id, record)
        counts["chess_games_created" if created else "chess_games_updated"] += 1

    puzzle_by_source: dict[str, ChessPuzzle] = {}
    for record in payload.get("puzzle_seeds", []):
        external_id = _text(record.get("id") or record.get("signature"), limit=120)
        fen = _text(record.get("fen"), limit=200)
        if not external_id or not fen:
            counts["chess_puzzles_skipped"] += 1
            continue
        puzzle = db.session.scalar(
            select(ChessPuzzle).where(ChessPuzzle.external_id == external_id)
        )
        created = puzzle is None
        context = record.get("game_context") if isinstance(record.get("game_context"), dict) else {}
        if puzzle is None:
            puzzle = ChessPuzzle(external_id=external_id, fen=fen)
            db.session.add(puzzle)
            db.session.flush()
        puzzle.source = _text(record.get("source"), limit=30) or "legacy"
        puzzle.fen = fen
        puzzle.moves = [str(move) for move in record.get("moves") or context.get("moves") or []]
        puzzle.themes = [_text(record.get("line_label"))] if record.get("line_label") else []
        puzzle.opening_tags = [
            item
            for item in (_text(record.get("opening_eco")), _text(record.get("opening_name")))
            if item
        ]
        puzzle_by_source[external_id] = puzzle
        _remember("chess_puzzle", external_id, puzzle.id, record)
        counts["chess_puzzles_created" if created else "chess_puzzles_updated"] += 1

    candidates = {
        _text(item.get("id")): _text(item.get("saved_seed_id"))
        for item in payload.get("auto_puzzle_candidates", [])
    }
    fallback = next(iter(puzzle_by_source.values()), None)
    for record in payload.get("puzzle_attempts", []):
        source_id = _text(record.get("id"))
        seed_id = candidates.get(_text(record.get("candidate_id")), "")
        puzzle = puzzle_by_source.get(seed_id) or fallback
        if not source_id or puzzle is None:
            counts["puzzle_attempts_skipped"] += 1
            continue
        mapped = db.session.scalar(
            select(LegacyIdMap).where(
                LegacyIdMap.source_system == "FlaskDashboard",
                LegacyIdMap.entity_type == "puzzle_attempt",
                LegacyIdMap.source_id == source_id,
            )
        )
        if mapped:
            counts["puzzle_attempts_existing"] += 1
            continue
        attempt = PuzzleAttempt(
            puzzle_id=puzzle.id,
            status=_text(record.get("status"), limit=30) or "completed",
            wrong_count=_integer(record.get("wrong_count")),
            reveal_used=bool(record.get("reveal_used")),
            completed_clean=bool(record.get("completed_clean")),
            needs_repeat=bool(record.get("needs_repeat")),
            due_at=_datetime(record.get("next_due_at")),
            started_at=_datetime(record.get("started_at")) or utc_now(),
            completed_at=_datetime(record.get("completed_at")),
        )
        db.session.add(attempt)
        db.session.flush()
        _remember("puzzle_attempt", source_id, attempt.id, record)
        counts["puzzle_attempts_created"] += 1


def _import_learning_and_history(source: Path, counts: Counter[str]) -> None:
    playlists = _json(source / "playlists.json", {})
    german = playlists.get("German", {})
    if isinstance(german, dict):
        for category, items in german.items():
            for record in items if isinstance(items, list) else []:
                title = _text(record.get("name"), limit=400)
                url = _text(record.get("url"), limit=1000)
                if not title:
                    continue
                resource = db.session.scalar(
                    select(GermanResource).where(
                        GermanResource.title == title, GermanResource.url == url
                    )
                )
                if resource is None:
                    db.session.add(
                        GermanResource(
                            title=title,
                            kind="playlist",
                            url=url,
                            source="FlaskDashboard",
                            description=f"Legacy {category} playlist",
                            metadata_json={"category": category},
                        )
                    )
                    counts["german_resources_created"] += 1
    for record in playlists.get("Chess", []):
        title = _text(record.get("name"), limit=300)
        if not title:
            continue
        course = db.session.scalar(select(ChessCourse).where(ChessCourse.title == title))
        if course is None:
            db.session.add(
                ChessCourse(
                    title=title,
                    category="playlist",
                    status="planned",
                    lines=[{"url": _text(record.get("url"), limit=1000)}],
                )
            )
            counts["chess_courses_created"] += 1

    deleted = _json(source / "deleted_history.json", [])
    for record in deleted if isinstance(deleted, list) else []:
        source_id = _text(record.get("video_id") or record.get("playlist_item_id"))
        if not source_id:
            continue
        mapped = db.session.scalar(
            select(LegacyIdMap).where(
                LegacyIdMap.source_system == "FlaskDashboard",
                LegacyIdMap.entity_type == "deleted_video",
                LegacyIdMap.source_id == source_id,
            )
        )
        if mapped:
            continue
        event = HistoryEvent(
            domain="youtube",
            entity_type="video",
            entity_id=source_id[:64],
            event_type="removed_from_source",
            label=_text(record.get("title"), limit=500) or "Removed legacy video",
            metadata_json={"playlist": _text(record.get("playlist_name"), limit=240)},
            created_at=_datetime(record.get("deleted_at")) or utc_now(),
        )
        db.session.add(event)
        db.session.flush()
        _remember("deleted_video", source_id, event.id, record)
        counts["history_events_created"] += 1


def _chat_count(source: Path) -> int:
    path = source / "chat_history.db"
    if not path.exists():
        return 0
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT COUNT(*) FROM chat_history").fetchone()
        return int(row[0]) if row else 0
    finally:
        connection.close()


def apply_legacy_import(source: str | Path, project_root: str | Path) -> dict[str, Any]:
    source_root = Path(source).expanduser().resolve(strict=True)
    target_root = Path(project_root).expanduser().resolve()
    if not source_root.is_dir():
        raise ValueError("Legacy source must be a directory.")
    if source_root == target_root or target_root in source_root.parents:
        raise ValueError("Legacy source and target must be separate directories.")

    counts = _copy_private_files(source_root, target_root)
    counts["archived_chat_messages"] = _chat_count(source_root)
    _import_movies(source_root, counts)
    _import_reading(source_root, counts)
    _import_books(source_root, counts)
    _import_pockettube(source_root, counts)
    _import_chess(source_root, counts)
    _import_learning_and_history(source_root, counts)
    db.session.commit()

    report = {
        "schema_version": "dragon-legacy-import.v1",
        "completed_at": utc_iso(),
        "source_label": source_root.name,
        "counts": dict(sorted(counts.items())),
        "secrets": "copied locally; values omitted",
    }
    report_root = target_root / "instance" / "migration"
    report_root.mkdir(parents=True, exist_ok=True)
    (report_root / "legacy-import-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report
