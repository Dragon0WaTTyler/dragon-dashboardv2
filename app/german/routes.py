from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.german.models import GermanResource, VocabularyItem
from app.german.services import GermanService

bp = Blueprint("german", __name__, url_prefix="/german")


@bp.get("")
@login_required
def index():
    kind = str(request.args.get("kind") or "")
    return render_template(
        "german/index.html",
        active_module="more",
        workspace=GermanService.workspace(kind=kind),
        kind=kind,
    )


@bp.post("/resources/<resource_id>/progress")
@login_required
def progress(resource_id: str):
    resource = db.session.get(GermanResource, resource_id)
    if resource is None:
        abort(404)
    try:
        GermanService.save_progress(resource, int(request.form.get("progress") or 0))
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("German lesson progress updated.", "success")
    return redirect(url_for("german.index"))


@bp.post("/vocabulary/<item_id>/review")
@login_required
def review(item_id: str):
    item = db.session.get(VocabularyItem, item_id)
    if item is None:
        abort(404)
    GermanService.review_word(item)
    flash("Vocabulary review saved.", "success")
    return redirect(url_for("german.index"))
