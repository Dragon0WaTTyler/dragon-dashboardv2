from __future__ import annotations

import hashlib
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.extensions import db
from app.movies.providers import TmdbIdentityError, TmdbIdentityProvider
from app.movies.public import get_playback_context, save_playback_external_ids
from app.playback.models import MagnetCandidate
from app.playback.runtime import (
    PlaybackRuntimeError,
    build_playback_manager,
)
from app.playback.services import PlaybackService
from app.playback.subtitles import (
    FallbackSubtitleProvider,
    SubtitleProviderError,
    build_subtitle_providers,
)
from app.services.streaming import transcode_stream

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
        and (
            current_app.extensions.get("dragon_subtitle_provider") is not None
            or current_app.config.get("DRAGON_WYZIE_API_KEY")
            or current_app.config.get("DRAGON_SUBDL_API_KEY")
        )
    ):
        abort(404)


def _subtitle_providers():
    providers = current_app.extensions.get("dragon_subtitle_providers")
    if providers is not None:
        return providers
    injected = current_app.extensions.get("dragon_subtitle_provider")
    if injected is not None:
        providers = {"default": injected}
    else:
        providers = {
            provider.name: provider
            for provider in build_subtitle_providers(current_app.config)
        }
    current_app.extensions["dragon_subtitle_providers"] = providers
    return providers


def _subtitle_search_provider():
    provider = current_app.extensions.get("dragon_subtitle_search_provider")
    if provider is not None:
        return provider
    injected = current_app.extensions.get("dragon_subtitle_provider")
    if injected is not None:
        provider = injected
    else:
        providers = list(_subtitle_providers().values())
        if not providers:
            abort(404)
        provider = providers[0] if len(providers) == 1 else FallbackSubtitleProvider(providers)
    current_app.extensions["dragon_subtitle_search_provider"] = provider
    return provider


def _subtitle_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="dragon-subtitle-track-v1")


def _subtitle_disk_cache_path(cache_key: str) -> Path:
    cache_dir = Path(current_app.instance_path) / "subtitle-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{hashlib.sha256(cache_key.encode()).hexdigest()}.vtt"


def _runtime_manager():
    manager = current_app.extensions.get("dragon_magnet_playback_manager")
    if manager is None:
        manager = build_playback_manager(
            instance_path=current_app.instance_path,
            cache_limit_gb=current_app.config["DRAGON_PLAYBACK_CACHE_GB"],
            cache_ttl_hours=current_app.config["DRAGON_PLAYBACK_CACHE_TTL_HOURS"],
        )
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
    season = _optional_positive_int(request.args.get("season"))
    episode = _optional_positive_int(request.args.get("episode"))
    episode_title = str(request.args.get("episode_title") or "").strip()[:160]
    if episode_title.casefold() == str(context.get("title") or "").strip().casefold():
        episode_title = ""
    try:
        candidates = _subtitle_search_provider().search(
            context,
            languages=current_app.config["DRAGON_SUBTITLE_LANGUAGES"],
            season=season,
            episode=episode,
            episode_title=episode_title,
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
                "provider": candidate.provider,
                "season": candidate.season,
                "episode": candidate.episode,
                "episode_title": candidate.episode_title,
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
    provider_name = str(payload.get("provider") or "default")
    season = _optional_positive_int(payload.get("season"))
    episode = _optional_positive_int(payload.get("episode"))
    episode_title = str(payload.get("episode_title") or "").strip()[:160]
    provider = _subtitle_providers().get(provider_name)
    if provider is None:
        abort(404)
    cache_key = (
        f"{provider_name}:{file_format}:{path}:{member_name}:{season or ''}:"
        f"{episode or ''}:{episode_title.casefold()}"
    )
    cache = current_app.extensions.setdefault("dragon_subtitle_cache", {})
    webvtt = cache.get(cache_key)
    if webvtt is None:
        disk_cache = None if current_app.config.get("TESTING") else _subtitle_disk_cache_path(cache_key)
        if disk_cache is not None and disk_cache.is_file():
            webvtt = disk_cache.read_bytes()
        else:
            try:
                webvtt = provider.download(
                    path,
                    file_format=file_format,
                    member_name=member_name,
                    season=season,
                    episode=episode,
                    episode_title=episode_title,
                )
            except SubtitleProviderError as exc:
                return current_app.response_class(str(exc), status=503, mimetype="text/plain")
            if disk_cache is not None:
                disk_cache.write_bytes(webvtt)
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
    metadata = dict(source.metadata_json or {})
    target_season = _optional_positive_int(payload.get("season")) or _optional_positive_int(
        metadata.get("season")
    )
    target_episode = _optional_positive_int(payload.get("episode")) or _optional_positive_int(
        metadata.get("episode")
    )
    torrent_fallback = PlaybackService.torrent_fallback(movie_id=movie_id, label=source.label)
    try:
        session = _runtime_manager().start(
            movie_id=movie_id,
            user_id=str(current_user.get_id()),
            source_id=source.id,
            magnet=source.locator,
            torrent_url=torrent_fallback.locator if torrent_fallback is not None else "",
            origin=request.host_url.rstrip("/"),
            season=target_season,
            episode=target_episode,
        )
    except PlaybackRuntimeError as exc:
        return jsonify({"ok": False, "error": {"message": str(exc)}}), 400
    return (
        jsonify(
            {
                "ok": True,
                "session": session,
                "status_url": url_for("playback.local_status", session_id=session["id"]),
                "stream_url": session.get("stream_url"),
                "transcode_url": url_for(
                    "playback.local_transcode", session_id=session["id"]
                ),
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
    response = jsonify(
        {
            "ok": True,
            "session": {
                **status,
                "transcode_url": url_for(
                    "playback.local_transcode", session_id=session_id
                ),
            },
        }
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.get("/runtime/<session_id>/transcode")
@login_required
def local_transcode(session_id: str):
    _require_local_player()
    try:
        status = _runtime_manager().status(session_id, user_id=str(current_user.get_id()))
    except PlaybackRuntimeError as exc:
        return jsonify({"ok": False, "error": {"message": str(exc)}}), 404
    stream_url = str(status.get("stream_url") or "").strip()
    if status.get("state") != "ready" or not stream_url:
        return jsonify(
            {"ok": False, "error": {"message": "Local stream is not ready yet."}}
        ), 409
    start_raw = str(request.args.get("start") or "").strip()
    start_seconds = None
    if start_raw:
        try:
            start_seconds = max(0.0, float(start_raw))
        except ValueError:
            return jsonify(
                {"ok": False, "error": {"message": "Invalid transcode start position."}}
            ), 400
    origin = request.host_url.rstrip("/")
    return transcode_stream(
        stream_url,
        allow_private=True,
        input_headers={"Origin": origin},
        start_seconds=start_seconds,
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


def _optional_positive_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
