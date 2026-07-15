from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
)
from flask_login import current_user, login_required
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.extensions import db
from app.movies.providers import TmdbIdentityError, TmdbIdentityProvider
from app.movies.public import get_playback_context, save_playback_external_ids
from app.playback.models import MagnetCandidate
from app.playback.runtime import (
    STREAM_CHUNK_BYTES,
    PlaybackNotReady,
    PlaybackRuntimeError,
    build_playback_manager,
)
from app.playback.services import PlaybackService
from app.playback.subtitles import SubdlSubtitleProvider, SubtitleProviderError

bp = Blueprint("playback", __name__, url_prefix="/playback")


def _require_playback() -> None:
    if not current_app.config["DRAGON_PLAYBACK_ENABLED"]:
        abort(404)


def _require_vidsrc() -> None:
    _require_playback()
    if not current_app.config["DRAGON_VIDSRC_ENABLED"]:
        abort(404)


def _require_local_player() -> None:
    _require_playback()
    if not current_app.config["DRAGON_MAGNETS_ENABLED"]:
        abort(404)


def _require_subtitles() -> None:
    _require_playback()
    if not (
        current_app.config["DRAGON_SUBTITLES_ENABLED"]
        and current_app.config["DRAGON_SUBDL_API_KEY"]
    ):
        abort(404)


def _subtitle_provider():
    provider = current_app.extensions.get("dragon_subtitle_provider")
    if provider is None:
        provider = SubdlSubtitleProvider(current_app.config["DRAGON_SUBDL_API_KEY"])
        current_app.extensions["dragon_subtitle_provider"] = provider
    return provider


def _subtitle_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="dragon-subtitle-track-v1")


def _runtime_manager():
    manager = current_app.extensions.get("dragon_magnet_playback_manager")
    if manager is None:
        manager = build_playback_manager(instance_path=current_app.instance_path)
        current_app.extensions["dragon_magnet_playback_manager"] = manager
    return manager


@bp.get("/movie/<movie_id>/vidsrc")
@login_required
def vidsrc_source(movie_id: str):
    _require_vidsrc()
    context = get_playback_context(movie_id)
    if context is None:
        abort(404)
    resolver = current_app.extensions.get("dragon_tmdb_identity_provider")
    if resolver is None:
        resolver = TmdbIdentityProvider(
            api_key=current_app.config["DRAGON_TMDB_API_KEY"],
            read_access_token=current_app.config["DRAGON_TMDB_READ_ACCESS_TOKEN"],
        )
        current_app.extensions["dragon_tmdb_identity_provider"] = resolver
    try:
        resolved_ids = resolver.resolve(
            title=context["title"],
            year=context["year"],
            media_type=context["media_type"],
            external_ids=context["external_ids"],
        )
        context["external_ids"] = save_playback_external_ids(movie_id, resolved_ids) or {}
        source = PlaybackService.vidsrc_source(
            movie=context,
            base_url=current_app.config["DRAGON_VIDSRC_EMBED_URL"],
        )
    except (TmdbIdentityError, ValueError) as exc:
        response = jsonify(
            {
                "ok": False,
                "error": {
                    "code": "vidsrc_identity_unavailable",
                    "message": str(exc),
                },
            }
        )
        response.headers["Cache-Control"] = "private, no-store"
        return response, 503
    response = jsonify({"ok": True, "source": source})
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.get("/movie/<movie_id>/subtitles")
@login_required
def subtitle_options(movie_id: str):
    _require_subtitles()
    context = get_playback_context(movie_id)
    if context is None:
        abort(404)
    try:
        candidates = _subtitle_provider().search(
            context,
            languages=current_app.config["DRAGON_SUBTITLE_LANGUAGES"],
        )
    except SubtitleProviderError as exc:
        response = jsonify(
            {
                "ok": False,
                "error": {"code": "subtitles_unavailable", "message": str(exc)},
            }
        )
        response.headers["Cache-Control"] = "private, no-store"
        return response, 503

    serializer = _subtitle_serializer()
    items = []
    for candidate in candidates:
        token = serializer.dumps(
            {
                "movie_id": movie_id,
                "path": candidate.path,
                "format": candidate.file_format,
                "member": candidate.member_name,
                "language": candidate.language,
            }
        )
        items.append(
            {
                "language": candidate.language,
                "language_name": candidate.language_name,
                "label": candidate.label,
                "hearing_impaired": candidate.hearing_impaired,
                "track_url": url_for("playback.subtitle_track", movie_id=movie_id, token=token),
            }
        )
    response = jsonify({"ok": True, "items": items})
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.get("/movie/<movie_id>/subtitles/track/<token>")
@login_required
def subtitle_track(movie_id: str, token: str):
    _require_subtitles()
    if get_playback_context(movie_id) is None:
        abort(404)
    try:
        payload = _subtitle_serializer().loads(token, max_age=12 * 60 * 60)
    except (BadSignature, SignatureExpired):
        abort(404)
    if not isinstance(payload, dict) or payload.get("movie_id") != movie_id:
        abort(404)
    path = str(payload.get("path") or "")
    file_format = str(payload.get("format") or "")
    member_name = str(payload.get("member") or "")
    cache_key = f"{file_format}:{path}:{member_name}"
    cache = current_app.extensions.setdefault("dragon_subtitle_cache", {})
    webvtt = cache.get(cache_key)
    if webvtt is None:
        try:
            webvtt = _subtitle_provider().download(
                path, file_format=file_format, member_name=member_name
            )
        except SubtitleProviderError as exc:
            return current_app.response_class(str(exc), status=503, mimetype="text/plain")
        if len(cache) >= 32:
            cache.pop(next(iter(cache)))
        cache[cache_key] = webvtt
    response = current_app.response_class(webvtt, mimetype="text/vtt")
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@bp.post("/movie/<movie_id>/local")
@login_required
def start_local_source(movie_id: str):
    _require_local_player()
    if get_playback_context(movie_id) is None:
        abort(404)
    payload = request.get_json(silent=True) or {}
    source_id = str(payload.get("source_id") or "").strip()
    source = PlaybackService.magnet_source(movie_id=movie_id, source_id=source_id)
    if source is None:
        abort(404)
    torrent_fallback = PlaybackService.torrent_fallback(movie_id=movie_id, label=source.label)
    try:
        session = _runtime_manager().start(
            movie_id=movie_id,
            user_id=str(current_user.get_id()),
            source_id=source.id,
            magnet=source.locator,
            torrent_url=torrent_fallback.locator if torrent_fallback is not None else "",
        )
    except PlaybackRuntimeError as exc:
        return jsonify({"ok": False, "error": {"message": str(exc)}}), 400
    return (
        jsonify(
            {
                "ok": True,
                "session": session,
                "status_url": url_for("playback.local_status", session_id=session["id"]),
                "stream_url": url_for("playback.local_stream", session_id=session["id"]),
                "stop_url": url_for("playback.stop_local", session_id=session["id"]),
            }
        ),
        202,
    )


@bp.get("/runtime/<session_id>")
@login_required
def local_status(session_id: str):
    _require_local_player()
    try:
        status = _runtime_manager().status(session_id, user_id=str(current_user.get_id()))
    except PlaybackRuntimeError as exc:
        return jsonify({"ok": False, "error": {"message": str(exc)}}), 404
    response = jsonify({"ok": True, "session": status})
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.route("/runtime/<session_id>/stream", methods=["GET", "HEAD"])
@login_required
def local_stream(session_id: str):
    _require_local_player()
    user_id = str(current_user.get_id())
    manager = _runtime_manager()
    try:
        stream_range = manager.open_range(
            session_id,
            user_id=user_id,
            range_header=str(request.headers.get("Range") or ""),
        )
    except PlaybackNotReady as exc:
        response = jsonify({"ok": False, "error": {"message": str(exc)}})
        response.status_code = 425
        response.headers["Retry-After"] = "1"
        return response
    except PlaybackRuntimeError as exc:
        return jsonify({"ok": False, "error": {"message": str(exc)}}), 416

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(stream_range.length),
        "Content-Range": f"bytes {stream_range.start}-{stream_range.end}/{stream_range.total}",
        "Cache-Control": "private, no-store",
    }
    if request.method == "HEAD":
        return current_app.response_class(
            status=206, headers=headers, mimetype=stream_range.mime_type
        )

    def generate():
        position = stream_range.start
        while position <= stream_range.end:
            chunk_end = min(position + STREAM_CHUNK_BYTES - 1, stream_range.end)
            yield manager.read_chunk(
                session_id,
                user_id=user_id,
                start=position,
                end=chunk_end,
            )
            position = chunk_end + 1

    return current_app.response_class(
        stream_with_context(generate()),
        status=206,
        headers=headers,
        mimetype=stream_range.mime_type,
    )


@bp.post("/runtime/<session_id>/stop")
@login_required
def stop_local(session_id: str):
    _require_local_player()
    try:
        _runtime_manager().stop(session_id, user_id=str(current_user.get_id()))
    except PlaybackRuntimeError as exc:
        return jsonify({"ok": False, "error": {"message": str(exc)}}), 404
    return jsonify({"ok": True})


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
