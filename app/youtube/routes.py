from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import login_required

from app.youtube.providers import YouTubePlaylistClient
from app.youtube.repositories import YouTubeRepository
from app.youtube.services import ORDERS, SOURCES, YouTubeService

bp = Blueprint("youtube", __name__, url_prefix="/youtube")


def _positive_int(value: str | None, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(value or default), maximum))
    except (TypeError, ValueError):
        return default


def _safe_return_to(value: str | None, *, fallback: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return fallback
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc or parsed.path != url_for("youtube.index"):
        return fallback
    return candidate


def _playlist_client() -> YouTubePlaylistClient:
    injected = current_app.extensions.get("dragon_youtube_playlist_client")
    if injected is not None:
        return injected
    return YouTubePlaylistClient(
        current_app.config["DRAGON_YOUTUBE_API_KEY"],
        oauth_token_path=Path(current_app.instance_path) / "secrets" / "youtube_token.json",
    )


def _oauth_redirect_uri() -> str:
    return url_for("youtube.oauth_callback", _external=True)


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
    if source == "pockettube" and group:
        group = YouTubeRepository.resolve_group(group)
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
    return_to = url_for(
        "youtube.index",
        source=source,
        group=group or None,
        q=q or None,
        order=order if order != "normal" else None,
        view=view if view != "grid" else None,
        page=page if page > 1 else None,
        per_page=per_page if per_page != 50 else None,
        seed=feed["seed"] if order in {"shuffle", "shuffle_video"} else None,
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
        return_to=return_to,
        sync_status=YouTubeService.sync_status(source),
        sync_available=bool(current_app.config["DRAGON_YOUTUBE_SYNC_ENABLED"]),
    )


@bp.post("/sync")
@login_required
def sync_watch_later():
    from app.shared.refresh import OperationCoordinator

    operation = OperationCoordinator.run(kind="sync", domain="youtube_watch_later")
    counts = dict(operation.counts or {})
    if operation.status == "failed":
        flash(
            f"YouTube sync failed: {operation.safe_error or 'your cached videos are unchanged.'}",
            "error",
        )
    elif operation.warnings:
        flash("YouTube playlist sync is not configured yet.", "warning")
    else:
        flash(
            f'Playlist synced: {counts.get("videos", 0)} active videos, '
            f'{counts.get("created", 0)} new, {counts.get("updated", 0)} updated, '
            f'{counts.get("removed", 0)} removed.',
            "success",
        )
    return redirect(
        _safe_return_to(
            request.form.get("return_to"),
            fallback=url_for("youtube.index", source="watch_later"),
        )
    )


@bp.post("/sync-pockettube")
@login_required
def sync_pockettube():
    from app.shared.refresh import OperationCoordinator

    operation = OperationCoordinator.run(kind="sync", domain="youtube_pockettube")
    counts = dict(operation.counts or {})
    if operation.status == "failed":
        flash("PocketTube sync failed. Your cached groups are unchanged.", "error")
    elif operation.warnings:
        flash(operation.warnings[0], "warning")
    else:
        flash(
            f'PocketTube synced: {counts.get("videos", 0)} latest videos from '
            f'{counts.get("channels", 0)} channels, {counts.get("created", 0)} new, '
            f'{counts.get("updated", 0)} updated, '
            f'{counts.get("shorts_skipped", 0)} shorts skipped.',
            "success",
        )
    return redirect(
        _safe_return_to(
            request.form.get("return_to"),
            fallback=url_for("youtube.index", source="pockettube"),
        )
    )


@bp.get("/connect")
@login_required
def oauth_connect():
    redirect_uri = _oauth_redirect_uri()
    state = secrets.token_urlsafe(32)
    session["youtube_oauth_state"] = state
    try:
        return redirect(_playlist_client().authorization_url(redirect_uri, state))
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("youtube.index", source="watch_later"))


@bp.get("/oauth/callback")
@login_required
def oauth_callback():
    expected_state = str(session.pop("youtube_oauth_state", ""))
    received_state = str(request.args.get("state") or "")
    if not expected_state or not secrets.compare_digest(expected_state, received_state):
        flash("YouTube connection could not be verified. Start the connection again.", "error")
        return redirect(url_for("youtube.index", source="watch_later"))
    provider_error = str(request.args.get("error") or "").strip()
    if provider_error:
        flash("YouTube connection was cancelled or denied.", "warning")
        return redirect(url_for("youtube.index", source="watch_later"))
    try:
        _playlist_client().exchange_authorization_code(
            str(request.args.get("code") or ""), _oauth_redirect_uri()
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("youtube.index", source="watch_later"))
    flash("YouTube is connected. You can refresh your local snapshot now.", "success")
    return redirect(url_for("youtube.index", source="watch_later"))


@bp.get("/<video_id>")
@login_required
def detail(video_id: str):
    video = YouTubeRepository.get(video_id)
    if video is None:
        abort(404)
    context = YouTubeService.detail_page(video)
    fallback = url_for("youtube.index", source=video.source, group=video.group_name or None)
    return_to = _safe_return_to(request.args.get("return_to"), fallback=fallback)
    return render_template(
        "youtube/detail.html",
        active_module="youtube",
        return_to=return_to,
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
    fallback = url_for("youtube.index", source=video.source, group=video.group_name or None)
    return_to = _safe_return_to(request.form.get("return_to"), fallback=fallback)
    return redirect(url_for("youtube.detail", video_id=video.id, return_to=return_to))


@bp.post("/<video_id>/remove")
@login_required
def remove(video_id: str):
    video = YouTubeRepository.get(video_id)
    if video is None:
        abort(404)
    fallback = url_for("youtube.index", source="watch_later")
    return_to = _safe_return_to(request.form.get("return_to"), fallback=fallback)
    if request.form.get("confirmed") != "yes":
        flash("Confirm removal to delete this video from the real YouTube playlist.", "warning")
        return redirect(url_for("youtube.detail", video_id=video.id, return_to=return_to))
    if not current_app.config["DRAGON_YOUTUBE_DELETE_ENABLED"]:
        flash(
            "YouTube deletion is disabled. The video remains both locally and on YouTube.",
            "warning",
        )
        return redirect(url_for("youtube.detail", video_id=video.id, return_to=return_to))
    try:
        YouTubeService.remove_from_watch_later(video, _playlist_client())
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("youtube.detail", video_id=video.id, return_to=return_to))
    flash("Removed from your YouTube Watch Later playlist. Local history was preserved.", "success")
    return redirect(return_to)
