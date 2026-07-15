from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.youtube.repositories import YouTubeRepository
from app.youtube.services import ORDERS, SOURCES, YouTubeService, video_detail

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
    page = _positive_int(request.args.get("page"), 1, 100000)
    per_page = _positive_int(request.args.get("per_page"), 50, 100)
    errors = {}
    if source not in SOURCES:
        errors["source"] = "Unknown source."
        source = "watch_later"
    if order not in ORDERS:
        errors["order"] = "Unknown order."
        order = "normal"
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
    related, _ = YouTubeRepository.list(
        source=video.source, group=video.group_name, limit=5
    )
    return render_template(
        "youtube/detail.html",
        active_module="youtube",
        video=video_detail(video),
        related=[video_detail(item) for item in related if item.id != video.id][:4],
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
