from __future__ import annotations

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.reading.repositories import ReadingRepository
from app.reading.services import ReadingService, article_detail, article_item

bp = Blueprint("reading", __name__, url_prefix="/reading")


@bp.get("")
@login_required
def index():
    q = str(request.args.get("q") or "")
    source_id = str(request.args.get("source") or "")
    status = str(request.args.get("status") or "")
    view = str(request.args.get("view") or "grid")
    if view not in {"grid", "list"}:
        view = "grid"
    articles = ReadingRepository.list(q=q, source_id=source_id, status=status)
    return render_template(
        "reading/index.html",
        active_module="reading",
        articles=[article_item(article) for article in articles],
        sources=ReadingRepository.sources(),
        q=q,
        source_id=source_id,
        status=status,
        view=view,
    )


@bp.get("/<article_id>")
@login_required
def detail(article_id: str):
    article = ReadingRepository.get(article_id)
    if article is None:
        abort(404)
    return render_template(
        "reading/detail.html", active_module="reading", article=article_detail(article)
    )


@bp.post("/<article_id>/status")
@login_required
def update_status(article_id: str):
    article = ReadingRepository.get(article_id)
    if article is None:
        abort(404)
    try:
        ReadingService.set_status(article, str(request.form.get("status") or ""))
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Reading progress updated.", "success")
    return redirect(url_for("reading.detail", article_id=article.id))


@bp.get("/<article_id>/fulltext-status")
@login_required
def fulltext_status(article_id: str):
    article = ReadingRepository.get(article_id)
    if article is None:
        abort(404)
    return ReadingService.extraction_status(article)


@bp.post("/<article_id>/extract-fulltext")
@login_required
def extract_fulltext(article_id: str):
    article = ReadingRepository.get(article_id)
    if article is None:
        abort(404)
    extractor = current_app.extensions.get("dragon_article_extractor")
    if not current_app.config["DRAGON_EXTERNAL_SYNC_ENABLED"] or extractor is None:
        flash("Full-text extraction is unavailable. Open the original source instead.", "warning")
        return redirect(url_for("reading.detail", article_id=article.id))
    try:
        ReadingService.extract_fulltext(article, extractor)
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Full article text cached locally.", "success")
    return redirect(url_for("reading.detail", article_id=article.id))
