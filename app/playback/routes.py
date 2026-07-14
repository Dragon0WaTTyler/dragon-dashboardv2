from __future__ import annotations

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.movies.public import get_playback_context
from app.playback.models import MagnetCandidate
from app.playback.services import PlaybackService

bp = Blueprint("playback", __name__, url_prefix="/playback")


def _require_playback() -> None:
    if not current_app.config["DRAGON_PLAYBACK_ENABLED"]:
        abort(404)


@bp.get("/movie/<movie_id>")
@login_required
def movie(movie_id: str):
    _require_playback()
    context = get_playback_context(movie_id)
    if context is None:
        abort(404)
    return render_template(
        "playback/movie.html",
        active_module="movies",
        movie=context,
        workspace=PlaybackService.workspace(movie_id),
        magnets_enabled=current_app.config["DRAGON_MAGNETS_ENABLED"],
    )


@bp.post("/movie/<movie_id>/sources/local")
@login_required
def add_local_source(movie_id: str):
    _require_playback()
    if get_playback_context(movie_id) is None:
        abort(404)
    try:
        PlaybackService.add_local_file(
            movie_id=movie_id,
            path_value=str(request.form.get("path") or ""),
            label=str(request.form.get("label") or ""),
        )
    except (OSError, ValueError) as exc:
        flash(str(exc), "error")
    else:
        flash("Local playback source added.", "success")
    return redirect(url_for("playback.movie", movie_id=movie_id))


@bp.post("/movie/<movie_id>/magnets")
@login_required
def add_magnet(movie_id: str):
    _require_playback()
    if not current_app.config["DRAGON_MAGNETS_ENABLED"]:
        abort(404)
    if get_playback_context(movie_id) is None:
        abort(404)
    try:
        PlaybackService.add_magnet(
            movie_id=movie_id, magnet_uri=str(request.form.get("magnet_uri") or "")
        )
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Magnet candidate saved for review. Nothing was downloaded.", "success")
    return redirect(url_for("playback.movie", movie_id=movie_id))


@bp.post("/magnets/<candidate_id>/approve")
@login_required
def approve_magnet(candidate_id: str):
    _require_playback()
    if not current_app.config["DRAGON_MAGNETS_ENABLED"]:
        abort(404)
    candidate = db.session.get(MagnetCandidate, candidate_id)
    if candidate is None:
        abort(404)
    PlaybackService.approve_magnet(candidate)
    flash("Magnet candidate approved. No client was launched.", "success")
    return redirect(url_for("playback.movie", movie_id=candidate.movie_id))
