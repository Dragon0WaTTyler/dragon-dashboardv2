from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.chess.repositories import ChessRepository
from app.chess.services import ChessService, game_detail, puzzle_item

bp = Blueprint("chess", __name__, url_prefix="/chess")


@bp.get("")
@login_required
def index():
    return render_template(
        "chess/index.html", active_module="chess", dashboard=ChessService.dashboard()
    )


@bp.get("/games/<game_id>")
@login_required
def game(game_id: str):
    record = ChessRepository.game(game_id)
    if record is None:
        abort(404)
    return render_template(
        "chess/game.html", active_module="chess", game=game_detail(record)
    )


@bp.get("/puzzles/<puzzle_id>")
@login_required
def puzzle(puzzle_id: str):
    record = ChessRepository.puzzle(puzzle_id)
    if record is None:
        abort(404)
    return render_template(
        "chess/puzzle.html", active_module="chess", puzzle=puzzle_item(record)
    )


@bp.post("/puzzles/<puzzle_id>/attempt")
@login_required
def puzzle_attempt(puzzle_id: str):
    puzzle_record = ChessRepository.puzzle(puzzle_id)
    if puzzle_record is None:
        abort(404)
    try:
        ChessService.complete_puzzle(
            puzzle_record,
            wrong_count=int(request.form.get("wrong_count") or 0),
            reveal_used=request.form.get("reveal_used") == "true",
            skipped=request.form.get("skipped") == "true",
        )
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Training attempt saved.", "success")
    return redirect(url_for("chess.puzzle", puzzle_id=puzzle_record.id))
