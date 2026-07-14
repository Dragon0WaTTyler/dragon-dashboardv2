from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.movies.repositories import MovieRepository
from app.movies.services import MovieService, movie_detail, movie_item, parse_movie_filters

bp = Blueprint("movies", __name__, url_prefix="/movies")


def _positive_int(value: str | None, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(value or default), maximum))
    except (TypeError, ValueError):
        return default


@bp.get("")
@login_required
def index():
    filters, errors = parse_movie_filters(request.args)
    page = _positive_int(request.args.get("page"), 1, 100000)
    per_page = _positive_int(request.args.get("per_page"), 24, 100)
    offset = (page - 1) * per_page
    movies, total = MovieRepository.list(filters, limit=per_page, offset=offset)
    return render_template(
        "movies/index.html",
        active_module="movies",
        movies=[movie_item(movie) for movie in movies],
        filters=filters,
        filter_errors=errors,
        filter_options=MovieRepository.filter_options(),
        page=page,
        per_page=per_page,
        total=total,
        has_previous=page > 1,
        has_next=offset + len(movies) < total,
    )


@bp.get("/<movie_id>")
@login_required
def detail(movie_id: str):
    movie = MovieRepository.get(movie_id)
    if movie is None:
        abort(404)
    return render_template(
        "movies/detail.html", active_module="movies", movie=movie_detail(movie)
    )


@bp.post("/<movie_id>/status")
@login_required
def update_status(movie_id: str):
    movie = MovieRepository.get(movie_id)
    if movie is None:
        abort(404)
    try:
        MovieService.set_status(movie, str(request.form.get("status") or ""))
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Movie status updated.", "success")
    return redirect(url_for("movies.detail", movie_id=movie_id))


@bp.post("/<movie_id>/score")
@login_required
def update_score(movie_id: str):
    movie = MovieRepository.get(movie_id)
    if movie is None:
        abort(404)
    raw_score = str(request.form.get("score") or "").strip()
    try:
        score = float(raw_score) if raw_score else None
        MovieService.set_score(movie, score)
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Personal score updated.", "success")
    return redirect(url_for("movies.detail", movie_id=movie_id))
