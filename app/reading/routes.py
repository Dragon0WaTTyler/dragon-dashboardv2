from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit

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
NEWS_PAGE_SIZE = 20


def _safe_reading_return_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.path != "/reading":
        return None
    return value


def _index_params(
    *,
    feed: str,
    q: str = "",
    source_id: str = "",
    status: str = "",
    view: str = "grid",
    sort: str = "recent",
    page: int = 1,
) -> dict[str, str | int]:
    params: dict[str, str | int] = {"feed": feed}
    if q:
        params["q"] = q
    if source_id:
        params["source"] = source_id
    if status:
        params["status"] = status
    if view != "grid":
        params["view"] = view
    if sort != "recent":
        params["sort"] = sort
    if page > 1:
        params["page"] = page
    return params


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
    page = request.args.get("page", 1, type=int) or 1
    if view not in {"grid", "list"}:
        view = "grid"
    if feed not in {"today", "recent", "saved", "sources"}:
        feed = "recent"
    if sort not in {"recent", "title"}:
        sort = "recent"
    page = max(page, 1)
    filters_active = bool(q or source_id or status or view != "grid" or sort != "recent")
    published_since = None
    if feed == "today":
        published_since = datetime.now().astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    filter_values = {
        "q": q,
        "source_id": source_id,
        "status": status,
        "published_since": published_since,
        "saved_only": feed == "saved",
    }
    query_values = {**filter_values, "sort": sort}
    total = 0 if feed == "sources" else ReadingRepository.count(**filter_values)
    if page > 1 and (page - 1) * NEWS_PAGE_SIZE >= total:
        page = max(1, (total - 1) // NEWS_PAGE_SIZE + 1) if total else 1
    articles = (
        []
        if feed == "sources"
        else ReadingRepository.list(
            **query_values,
            offset=(page - 1) * NEWS_PAGE_SIZE,
            limit=NEWS_PAGE_SIZE,
        )
    )
    index_params = _index_params(
        feed=feed, q=q, source_id=source_id, status=status, view=view, sort=sort, page=page
    )
    return_url = url_for("reading.index", **index_params)
    feed_links = [
        {
            "key": key,
            "label": label,
            "url": url_for(
                "reading.index",
                **_index_params(
                    feed=key,
                    q=q,
                    source_id=source_id,
                    status=status,
                    view=view,
                    sort=sort,
                ),
            ),
        }
        for key, label in (
            ("today", "Today"),
            ("recent", "Recent"),
            ("saved", "Saved"),
            ("sources", "Sources"),
        )
    ]
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
        page=page,
        page_size=NEWS_PAGE_SIZE,
        total=total,
        filters_active=filters_active,
        return_url=return_url,
        clear_url=url_for("reading.index", feed=feed),
        feed_links=feed_links,
        previous_url=(
            url_for(
                "reading.index",
                **_index_params(
                    feed=feed,
                    q=q,
                    source_id=source_id,
                    status=status,
                    view=view,
                    sort=sort,
                    page=page - 1,
                ),
            )
            if page > 1
            else None
        ),
        next_url=(
            url_for(
                "reading.index",
                **_index_params(
                    feed=feed,
                    q=q,
                    source_id=source_id,
                    status=status,
                    view=view,
                    sort=sort,
                    page=page + 1,
                ),
            )
            if page * NEWS_PAGE_SIZE < total
            else None
        ),
        continue_reading=(
            ReadingService.continue_reading(limit=3)
            if feed in {"today", "recent"} and not (q or source_id or status)
            else []
        ),
    )


@bp.get("/<article_id>")
@login_required
def detail(article_id: str):
    article = ReadingRepository.get(article_id)
    if article is None:
        abort(404)
    return render_template(
        "reading/detail.html",
        active_module="reading",
        article=article_detail(article),
        return_url=(
            _safe_reading_return_url(request.args.get("return_to"))
            or url_for("reading.index")
        ),
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
    return redirect(
        _safe_reading_return_url(request.form.get("return_to")) or url_for("reading.index")
    )


@bp.post("/sources")
@login_required
def create_source():
    from app.reading.source_manager import ReadingSourceManager, ReadingSourceValidationError

    try:
        ReadingSourceManager.create(request.form)
    except ReadingSourceValidationError as exc:
        flash(str(exc), "error")
    else:
        flash("RSS source added to your personal News workspace.", "success")
    return redirect(url_for("reading.index", feed="sources"))


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
    return redirect(
        url_for(
            "reading.detail",
            article_id=article.id,
            return_to=_safe_reading_return_url(request.form.get("return_to")),
        )
    )


@bp.post("/<article_id>/saved")
@login_required
def update_saved(article_id: str):
    article = ReadingRepository.get(article_id)
    if article is None:
        abort(404)
    saved = request.form.get("saved") == "true"
    ReadingService.set_saved(article, saved)
    flash("Saved for later." if saved else "Removed from saved.", "success")
    return redirect(
        url_for(
            "reading.detail",
            article_id=article.id,
            return_to=_safe_reading_return_url(request.form.get("return_to")),
        )
    )


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
    return_to = _safe_reading_return_url(request.args.get("return_to"))
    detail_url = url_for("reading.detail", article_id=article.id, return_to=return_to)
    if features.get("mark_read_automatically", True) and article.status == "unread":
        ReadingService.set_status(article, "reading")
    if article.fulltext_state == "cached" and article_content_is_readable(article):
        return redirect(detail_url)
    extractor = current_app.extensions.get("dragon_article_extractor")
    if extractor is None:
        flash("The full article is unavailable. You can still open the original source.", "warning")
        return redirect(detail_url)
    try:
        ReadingService.extract_fulltext(article, extractor)
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Full article loaded and cached locally.", "success")
    return redirect(detail_url)


@bp.post("/<article_id>/refresh")
@login_required
def refresh_article(article_id: str):
    article = ReadingRepository.get(article_id)
    if article is None:
        abort(404)
    extractor = current_app.extensions.get("dragon_article_extractor")
    if extractor is None:
        flash("Article refresh is unavailable. The saved copy is unchanged.", "warning")
        return redirect(
            url_for(
                "reading.detail",
                article_id=article.id,
                return_to=_safe_reading_return_url(request.form.get("return_to")),
            )
        )
    try:
        ReadingService.extract_fulltext(article, extractor)
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Article text refreshed from the original source.", "success")
    return redirect(
        url_for(
            "reading.detail",
            article_id=article.id,
            return_to=_safe_reading_return_url(request.form.get("return_to")),
        )
    )
