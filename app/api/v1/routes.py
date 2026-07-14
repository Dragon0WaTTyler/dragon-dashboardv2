from __future__ import annotations

from datetime import datetime

from flask import Blueprint, request
from flask_login import login_required
from sqlalchemy import text

from app.api.v1.responses import collection_response, error_response, item_response
from app.books.repositories import BookRepository
from app.books.services import book_detail, book_item
from app.chess.repositories import ChessRepository
from app.chess.services import ChessService, game_detail, game_item, puzzle_item
from app.extensions import db
from app.german.services import GermanService
from app.history.services import HistoryService, event_item
from app.movies.repositories import MovieRepository
from app.movies.services import (
    MovieService,
    ProgressConflictError,
    movie_detail,
    movie_item,
    parse_movie_filters,
    progress_dict,
)
from app.reading.repositories import ReadingRepository
from app.reading.services import ReadingService, article_detail, article_item
from app.shared.freshness import get_freshness, list_freshness
from app.shared.operations import OperationService
from app.today.services import TodayService
from app.youtube.repositories import YouTubeRepository
from app.youtube.services import ORDERS, SOURCES, YouTubeService, video_detail, video_item

bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")


@bp.get("/health")
def health():
    db.session.execute(text("SELECT 1"))
    return item_response({"status": "ok", "database": "available"})


@bp.get("/home")
@login_required
def home():
    return item_response(TodayService.workspace())


@bp.get("/freshness")
@login_required
def freshness_collection():
    items = list_freshness()
    return collection_response(items, total=len(items), limit=len(items), offset=0)


@bp.get("/freshness/<domain>")
@login_required
def freshness_detail(domain: str):
    return item_response(get_freshness(domain))


@bp.get("/operations/<operation_id>")
@login_required
def operation_detail(operation_id: str):
    operation = OperationService.get(operation_id)
    if operation is None:
        return error_response("not_found", "Operation not found.", 404)
    return item_response(operation.as_dict())


def _bounded_int(value: str | None, default: int, maximum: int) -> int:
    try:
        return max(0, min(int(value or default), maximum))
    except (TypeError, ValueError):
        return default


@bp.get("/movies")
@login_required
def movies_collection():
    filters, errors = parse_movie_filters(request.args)
    if errors:
        return error_response("validation_error", "Invalid movie filters.", 422, fields=errors)
    limit = _bounded_int(request.args.get("limit"), 24, 100)
    limit = max(limit, 1)
    offset = _bounded_int(request.args.get("offset"), 0, 1_000_000)
    movies, total = MovieRepository.list(filters, limit=limit, offset=offset)
    return collection_response(
        [movie_item(movie) for movie in movies], total=total, limit=limit, offset=offset
    )


@bp.get("/movies/<movie_id>")
@login_required
def movie_api_detail(movie_id: str):
    movie = MovieRepository.get(movie_id)
    if movie is None:
        return error_response("not_found", "Movie not found.", 404)
    return item_response(movie_detail(movie))


@bp.get("/playback-progress/movie/<movie_id>")
@login_required
def movie_progress_detail(movie_id: str):
    movie = MovieRepository.get(movie_id)
    if movie is None:
        return error_response("not_found", "Movie not found.", 404)
    return item_response({"movie_id": movie.id, "progress": progress_dict(movie.progress)})


@bp.put("/playback-progress/movie/<movie_id>")
@login_required
def update_movie_progress(movie_id: str):
    movie = MovieRepository.get(movie_id)
    if movie is None:
        return error_response("not_found", "Movie not found.", 404)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error_response("validation_error", "A JSON object is required.", 422)
    errors: dict[str, str] = {}
    values: dict[str, int] = {}
    for field in ("current_seconds", "duration_seconds"):
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            errors[field] = "Must be a non-negative integer."
        else:
            values[field] = value
    completed = payload.get("completed", False)
    if not isinstance(completed, bool):
        errors["completed"] = "Must be a boolean."
    client_updated_at = None
    if payload.get("client_updated_at"):
        try:
            client_updated_at = datetime.fromisoformat(
                str(payload["client_updated_at"]).replace("Z", "+00:00")
            )
        except ValueError:
            errors["client_updated_at"] = "Must be an ISO 8601 timestamp."
    if errors:
        return error_response("validation_error", "Invalid playback progress.", 422, fields=errors)
    try:
        progress = MovieService.save_progress(
            movie,
            current_seconds=values["current_seconds"],
            duration_seconds=values["duration_seconds"],
            completed=completed,
            client_updated_at=client_updated_at,
        )
    except ProgressConflictError as exc:
        return error_response(
            "progress_conflict", "A newer progress update is already stored.", 409,
            fields={"stored_progress": str(exc.progress)},
        )
    return item_response({"movie_id": movie.id, "progress": progress_dict(progress)})


@bp.get("/youtube")
@login_required
def youtube_collection():
    source = str(request.args.get("source") or "watch_later")
    order = str(request.args.get("order") or "normal")
    if source not in SOURCES or order not in ORDERS:
        return error_response("validation_error", "Invalid YouTube view.", 422)
    limit = max(_bounded_int(request.args.get("limit"), 50, 100), 1)
    offset = _bounded_int(request.args.get("offset"), 0, 1_000_000)
    videos, total = YouTubeRepository.list(
        source=source,
        group=str(request.args.get("group") or ""),
        q=str(request.args.get("q") or ""),
        limit=limit,
        offset=offset,
    )
    items = [video_item(video) for video in videos]
    if order == "shuffle_video":
        feed = YouTubeService.feed(source=source, order=order)
        items = feed["items"]
        total = feed["total"]
    return collection_response(items, total=total, limit=limit, offset=offset)


@bp.get("/youtube/<video_id>")
@login_required
def youtube_api_detail(video_id: str):
    video = YouTubeRepository.get(video_id)
    if video is None:
        return error_response("not_found", "Video not found.", 404)
    return item_response(video_detail(video))


@bp.get("/youtube/sections")
@login_required
def youtube_sections():
    groups = YouTubeRepository.groups()
    items = [
        {"id": "watch_later", "label": "Watch Later", "kind": "source"},
        {"id": "pockettube", "label": "PocketTube", "kind": "source"},
        *[{"id": item["name"], "label": item["name"], "kind": "group"} for item in groups],
    ]
    return collection_response(items, total=len(items), limit=len(items), offset=0)


@bp.get("/articles")
@login_required
def articles_collection():
    articles = ReadingRepository.list(
        q=str(request.args.get("q") or ""),
        source_id=str(request.args.get("source") or ""),
        status=str(request.args.get("status") or ""),
        limit=max(_bounded_int(request.args.get("limit"), 50, 100), 1),
    )
    items = [article_item(article) for article in articles]
    return collection_response(items, total=len(items), limit=len(items) or 1, offset=0)


@bp.get("/articles/<article_id>")
@login_required
def article_api_detail(article_id: str):
    article = ReadingRepository.get(article_id)
    if article is None:
        return error_response("not_found", "Article not found.", 404)
    return item_response(article_detail(article))


@bp.get("/articles/<article_id>/fulltext-status")
@login_required
def article_fulltext_status(article_id: str):
    article = ReadingRepository.get(article_id)
    if article is None:
        return error_response("not_found", "Article not found.", 404)
    return item_response(ReadingService.extraction_status(article))


@bp.get("/books")
@login_required
def books_collection():
    books = BookRepository.list(
        q=str(request.args.get("q") or ""), status=str(request.args.get("status") or "")
    )
    items = [book_item(book) for book in books]
    return collection_response(items, total=len(items), limit=len(items) or 1, offset=0)


@bp.get("/books/<book_id>")
@login_required
def book_api_detail(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        return error_response("not_found", "Book not found.", 404)
    return item_response(book_detail(book))


@bp.get("/chess")
@login_required
def chess_dashboard():
    dashboard = ChessService.dashboard()
    return item_response(
        {
            "recent_games": dashboard["games"],
            "training_queue": dashboard["puzzles"],
            "due_review": dashboard["due_review"],
            "courses": dashboard["courses"],
        }
    )


@bp.get("/chess/games")
@login_required
def chess_games():
    games = [game_item(game) for game in ChessRepository.games(100)]
    return collection_response(games, total=len(games), limit=100, offset=0)


@bp.get("/chess/games/<game_id>")
@login_required
def chess_game_detail(game_id: str):
    game = ChessRepository.game(game_id)
    if game is None:
        return error_response("not_found", "Chess game not found.", 404)
    return item_response(game_detail(game))


@bp.get("/chess/puzzles")
@login_required
def chess_puzzles():
    puzzles = [puzzle_item(puzzle) for puzzle in ChessRepository.puzzles(100)]
    return collection_response(puzzles, total=len(puzzles), limit=100, offset=0)


@bp.get("/german")
@login_required
def german_workspace():
    return item_response(GermanService.workspace(kind=str(request.args.get("kind") or "")))


@bp.get("/history")
@login_required
def history_collection():
    events = [
        event_item(event)
        for event in HistoryService.list(domain=str(request.args.get("domain") or ""))
    ]
    return collection_response(events, total=len(events), limit=100, offset=0)
