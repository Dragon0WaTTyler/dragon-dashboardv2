from __future__ import annotations

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.reading.repositories import ReadingRepository
from app.reading.services import (
    ReadingService,
    article_content_is_readable,
    article_detail,
    article_item,
)
from app.shared.refresh import OperationCoordinator

bp = Blueprint("reading", __name__, url_prefix="/reading")


@bp.get("")
@login_required
def index():
    from app.admin.control_center import preference_store

    preferences = preference_store().read()["sections"]["reading"]
    q = str(request.args.get("q") or "")
    source_id = str(request.args.get("source") or "")
    status = str(request.args.get("status") or "")
    view = str(request.args.get("view") or "grid")
    feed = str(request.args.get("feed") or preferences["default_view"])
    sort = str(request.args.get("sort") or preferences["default_sort"])
    if view not in {"grid", "list"}:
        view = "grid"
    if feed not in {"today", "recent", "saved", "sources"}:
        feed = "recent"
    if sort not in {"recent", "title"}:
        sort = "recent"
    if "status" not in request.args and feed == "saved":
        status = "saved"
    articles = (
        []
        if feed == "sources"
        else ReadingRepository.list(
            q=q,
            source_id=source_id,
            status=status,
            sort=sort,
        )
    )
    return render_template(
        "reading/index.html",
        active_module="reading",
        articles=[article_item(article) for article in articles],
        sources=ReadingRepository.sources(),
        q=q,
        source_id=source_id,
        status=status,
        view=view,
        feed=feed,
        sort=sort,
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


@bp.post("/sync")
@login_required
def sync_articles():
    operation = OperationCoordinator.run(kind="sync", domain="reading")
    counts = dict(operation.counts or {})
    if operation.status == "failed":
        flash("Article sync failed. Your saved articles are unchanged.", "error")
    elif operation.warnings:
        flash(
            f"Added {counts.get('created', 0)} new articles. "
            f"{counts.get('sources_failed', 0)} sources could not be reached.",
            "warning",
        )
    else:
        flash(
            f"Articles synced: {counts.get('created', 0)} new, {counts.get('updated', 0)} updated.",
            "success",
        )
    return redirect(url_for("reading.index"))


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


@bp.post("/<article_id>/open")
@login_required
def open_article(article_id: str):
    article = ReadingRepository.get(article_id)
    if article is None:
        abort(404)
    from app.admin.control_center import preference_store

    features = preference_store().read()["sections"]["reading"]["features"]
    if features.get("mark_read_automatically", True) and article.status == "unread":
        ReadingService.set_status(article, "reading")
    if article.fulltext_state == "cached" and article_content_is_readable(article):
        return redirect(url_for("reading.detail", article_id=article.id))
    extractor = current_app.extensions.get("dragon_article_extractor")
    if extractor is None:
        flash("The full article is unavailable. You can still open the original source.", "warning")
        return redirect(url_for("reading.detail", article_id=article.id))
    try:
        ReadingService.extract_fulltext(article, extractor)
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Full article loaded and cached locally.", "success")
    return redirect(url_for("reading.detail", article_id=article.id))


@bp.post("/<article_id>/refresh")
@login_required
def refresh_article(article_id: str):
    article = ReadingRepository.get(article_id)
    if article is None:
        abort(404)
    extractor = current_app.extensions.get("dragon_article_extractor")
    if extractor is None:
        flash("Article refresh is unavailable. The saved copy is unchanged.", "warning")
        return redirect(url_for("reading.detail", article_id=article.id))
    try:
        ReadingService.extract_fulltext(article, extractor)
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Article text refreshed from the original source.", "success")
    return redirect(url_for("reading.detail", article_id=article.id))
