from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import func

from app.books.models import Book
from app.extensions import db
from app.movies.models import Movie
from app.reading.models import ReadingSource
from app.shared.freshness import list_freshness
from app.shared.models import SnapshotRecord
from app.shared.operations import OperationService
from app.shared.refresh import OperationCoordinator

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.get("")
@login_required
def index():
    sources = list(db.session.scalars(db.select(ReadingSource).order_by(ReadingSource.name)))
    movie_review = int(
        db.session.scalar(
            db.select(func.count()).select_from(Movie).where(Movie.metadata_state != {})
        )
        or 0
    )
    book_review = int(
        db.session.scalar(
            db.select(func.count()).select_from(Book).where(Book.metadata_state != {})
        )
        or 0
    )
    snapshots = list(
        db.session.scalars(db.select(SnapshotRecord).order_by(SnapshotRecord.domain))
    )
    return render_template(
        "admin/index.html",
        active_module="more",
        freshness=list_freshness(),
        sources=sources,
        snapshots=snapshots,
        metadata_review_count=movie_review + book_review,
        operations=OperationService.list_recent(limit=8),
    )


@bp.post("/run")
@login_required
def run_operation():
    kind = str(request.form.get("kind") or "")
    domain = str(request.form.get("domain") or "")
    if kind == "sync" and domain == "all" and request.form.get("confirmed") != "yes":
        flash("Confirm the global synchronization before running it.", "warning")
        return redirect(url_for("admin.index"))
    try:
        operation = OperationCoordinator.run(kind=kind, domain=domain)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.index"))
    flash("Operation finished with a local report.", "success")
    return redirect(url_for("admin.operation_detail", operation_id=operation.id))


@bp.get("/design-system")
@login_required
def design_system():
    return render_template("admin/design_system.html", active_module="more")


@bp.get("/operations")
@login_required
def operations():
    return render_template(
        "admin/operations.html",
        active_module="more",
        operations=OperationService.list_recent(limit=50),
    )


@bp.get("/operations/<operation_id>")
@login_required
def operation_detail(operation_id: str):
    operation = OperationService.get(operation_id)
    if operation is None:
        abort(404)
    return render_template(
        "admin/operation_detail.html",
        active_module="more",
        operation=operation,
    )
