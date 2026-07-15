from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.youtube.repositories import YouTubeRepository
from app.youtube.services import ORDERS, SOURCES, YouTubeService

bp = Blueprint("youtube", __name__, url_prefix="/youtube")


def _positive_int(value: str | None, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(value or default), maximum))
    except (TypeError, ValueError):
        return default


@bp.get("")
@login_required
def index():
    source = str(request.args.get("source") or "watch_later")
    group = str(request.args.get("group") or "")
    q = str(request.args.get("q") or "")
    order = str(request.args.get("order") or "normal")
    view = str(request.args.get("view") or "grid")
    page = _positive_int(request.args.get("page"), 1, 100000)
    per_page = _positive_int(request.args.get("per_page"), 50, 100)
    errors = {}
    if source not in SOURCES:
        errors["source"] = "Unknown source."
        source = "watch_later"
    if order not in ORDERS:
        errors["order"] = "Unknown order."
        order = "normal"
    if view not in {"grid", "list"}:
        view = "grid"
    offset = (page - 1) * per_page
    feed = YouTubeService.feed(
        source=source,
        group=group,
        q=q,
        order=order,
        limit=per_page,
        offset=offset,
        seed=str(request.args.get("seed") or ""),
    )
    return render_template(
        "youtube/index.html",
        active_module="youtube",
        feed=feed,
        source=source,
        group=group,
        q=q,
        order=order,
        view=view,
        groups=YouTubeRepository.groups(),
        errors=errors,
        page=page,
        per_page=per_page,
        has_previous=page > 1,
        has_next=offset + len(feed["items"]) < feed["total"],
    )


@bp.get("/<video_id>")
@login_required
def detail(video_id: str):
    video = YouTubeRepository.get(video_id)
    if video is None:
        abort(404)
    context = YouTubeService.detail_page(video)
    return render_template(
        "youtube/detail.html",
        active_module="youtube",
        **context,
    )


@bp.post("/<video_id>/watched")
@login_required
def watched(video_id: str):
    video = YouTubeRepository.get(video_id)
    if video is None:
        abort(404)
    YouTubeService.set_watched(video, request.form.get("watched") == "true")
    flash("Video history updated.", "success")
    return redirect(url_for("youtube.detail", video_id=video.id))


@bp.post("/<video_id>/remove")
@login_required
def remove(video_id: str):
    video = YouTubeRepository.get(video_id)
    if video is None:
        abort(404)
    try:
        YouTubeService.remove_from_watch_later(video)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("youtube.detail", video_id=video.id))
    flash("Removed from Watch Later. Local history was preserved.", "success")
    return redirect(url_for("youtube.index", source="watch_later"))
