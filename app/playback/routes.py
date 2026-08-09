from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

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
from app.movies.public import get_playback_context, save_playback_external_ids, tv_episode_exists
from app.playback.catalog import (
    CatalogImportError,
    CatalogImportService,
    import_batch_report,
    parse_catalog_csv,
    parse_catalog_json,
)
from app.playback.identity import PlaybackIdentity
from app.playback.models import ImportBatch, MagnetCandidate, PlaybackSource
from app.playback.providers import (
    INDEXED_EMBED_PROVIDER_SPECS,
    build_provider_registry_from_config,
    validate_indexed_embed_url_template,
)
from app.playback.runtime import (
    PlaybackRuntimeError,
    build_playback_manager,
)
from app.playback.services import (
    AUTHORIZED_EMBED_AUTHORIZATION_STATUSES,
    PlaybackService,
    ProviderAvailabilityService,
)
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
    if not current_app.config["DRAGON_VIDSRC_ENABLED"] or not _provider_is_enabled("vidsrc"):
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
            provider.name: provider for provider in build_subtitle_providers(current_app.config)
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


def _provider_registry():
    registry = current_app.extensions.get("dragon_playback_provider_registry")
    if registry is None:
        registry = build_provider_registry_from_config(current_app.config)
        current_app.extensions["dragon_playback_provider_registry"] = registry
    return registry


def _provider_is_enabled(key: str) -> bool:
    return key in PlaybackService.enabled_provider_keys(_provider_registry().keys())


def _provider_priorities() -> dict[str, int]:
    return {
        key: int(preference["priority"])
        for key, preference in PlaybackService.provider_preferences(
            _provider_registry().keys()
        ).items()
    }


def _configured_embed_provider(key: str) -> tuple[bool, str]:
    """Return local configuration readiness without contacting a provider."""
    config_key = key.upper()
    if not current_app.config.get(f"DRAGON_{config_key}_ENABLED", False):
        return False, "disabled_in_config"
    base_url = str(current_app.config.get(f"DRAGON_{config_key}_EMBED_URL", "")).strip()
    try:
        validate_indexed_embed_url_template(key, base_url)
    except ValueError:
        return False, "invalid_or_missing_embed_template"
    parsed = urlsplit(base_url)
    try:
        port = parsed.port
    except ValueError:
        port = None
        invalid_port = True
    else:
        invalid_port = False
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or invalid_port
        or port == 0
    ):
        return False, "invalid_or_missing_embed_template"
    return True, ""


@bp.get("/movie/<movie_id>/vidsrc")
@login_required
def vidsrc_source(movie_id: str):
    _require_vidsrc()
    context = get_playback_context(movie_id)
    if context is None:
        abort(404)
    season = _optional_positive_int(request.args.get("season"))
    episode = _optional_positive_int(request.args.get("episode"))
    if (season is None) != (episode is None):
        return _playback_source_error(
            "TV playback requires both a season and an episode.",
            code="invalid_playback_scope",
            status=400,
        )
    if context["media_type"] == "tv" and (
        season is None
        or episode is None
        or not tv_episode_exists(movie_id, season=season, episode=episode)
    ):
        return _playback_source_error(
            "A valid TV season and episode are required for playback.",
            code="invalid_playback_scope",
            status=400,
        )
    if context["media_type"] != "tv" and (season is not None or episode is not None):
        return _playback_source_error(
            "Movie playback does not accept a TV season or episode.",
            code="invalid_playback_scope",
            status=400,
        )
    try:
        identity = PlaybackIdentity.from_context(context, season=season, episode=episode)
        if not identity.imdb_id and not identity.tmdb_id:
            resolver = current_app.extensions.get("dragon_tmdb_identity_provider")
            if resolver is None:
                resolver = TmdbIdentityProvider(
                    api_key=current_app.config["DRAGON_TMDB_API_KEY"],
                    read_access_token=current_app.config["DRAGON_TMDB_READ_ACCESS_TOKEN"],
                )
                current_app.extensions["dragon_tmdb_identity_provider"] = resolver
            resolved_ids = resolver.resolve(
                title=context["title"],
                year=context["year"],
                media_type=context["media_type"],
                external_ids=context["external_ids"],
            )
            context["external_ids"] = save_playback_external_ids(movie_id, resolved_ids) or {}
            identity = PlaybackIdentity.from_context(context, season=season, episode=episode)
        provider = _provider_registry().require("vidsrc")
        source = provider.resolve(identity)
        source_row = PlaybackService.upsert_resolved_source(identity=identity, resolved=source)
        availability = ProviderAvailabilityService.revalidate_if_stale(
            source_row,
            identity=identity,
            provider=provider,
        )
        if availability.status == "UNAVAILABLE":
            return _playback_source_error(
                "The selected source is currently unavailable.",
                code="source_unavailable",
                status=503,
            )
    except TmdbIdentityError as exc:
        return _playback_source_error(str(exc), code="vidsrc_identity_unavailable", status=503)
    except ValueError as exc:
        return _playback_source_error(str(exc), code="vidsrc_identity_unavailable", status=503)
    source_payload = source.response_item() | {"source_id": source_row.id}
    response = jsonify({"ok": True, "source": source_payload})
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.get("/movie/<movie_id>/sources")
@login_required
def playback_sources(movie_id: str):
    _require_playback()
    context = get_playback_context(movie_id)
    if context is None:
        abort(404)
    season = _optional_positive_int(request.args.get("season"))
    episode = _optional_positive_int(request.args.get("episode"))
    if (season is None) != (episode is None):
        return _playback_source_error(
            "TV playback requires both a season and an episode.",
            code="invalid_playback_scope",
            status=400,
        )
    if context["media_type"] == "tv" and (
        season is None
        or episode is None
        or not tv_episode_exists(movie_id, season=season, episode=episode)
    ):
        return _playback_source_error(
            "A valid TV season and episode are required for playback.",
            code="invalid_playback_scope",
            status=400,
        )
    response = jsonify(
        {
            "ok": True,
            "items": PlaybackService.indexed_embed_sources(
                movie_id,
                season=season,
                episode=episode,
                enabled_providers=PlaybackService.enabled_provider_keys(
                    _provider_registry().keys() - {"vidsrc"}
                ),
                provider_priorities=_provider_priorities(),
            ),
        }
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.get("/movie/<movie_id>/activation-status")
@login_required
def provider_activation_status(movie_id: str):
    """Expose local-only smoke-test readiness for one playback scope.

    This intentionally contains no provider URL and performs no third-party
    request. It exists so an operator can distinguish a missing mapping from a
    disabled or incomplete provider configuration before testing playback.
    """
    _require_playback()
    context = get_playback_context(movie_id)
    if context is None:
        abort(404)
    season = _optional_positive_int(request.args.get("season"))
    episode = _optional_positive_int(request.args.get("episode"))
    if (season is None) != (episode is None):
        return _playback_source_error(
            "TV playback requires both a season and an episode.",
            code="invalid_playback_scope",
            status=400,
        )
    if context["media_type"] == "tv" and (
        season is None
        or episode is None
        or not tv_episode_exists(movie_id, season=season, episode=episode)
    ):
        return _playback_source_error(
            "A valid TV season and episode are required for playback.",
            code="invalid_playback_scope",
            status=400,
        )
    if context["media_type"] != "tv" and (season is not None or episode is not None):
        return _playback_source_error(
            "Movie playback does not accept a TV season or episode.",
            code="invalid_playback_scope",
            status=400,
        )

    identity = PlaybackIdentity.from_context(context, season=season, episode=episode)
    indexed_rows = list(
        db.session.scalars(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie_id,
                PlaybackSource.kind == "embed",
                PlaybackSource.source_type == "known_embed",
                PlaybackSource.scope_key == identity.scope_key,
            )
        )
    )
    rows_by_provider: dict[str, list[PlaybackSource]] = {}
    for row in indexed_rows:
        rows_by_provider.setdefault(row.provider, []).append(row)
    provider_keys = {spec.key for spec in INDEXED_EMBED_PROVIDER_SPECS} | {"vidsrc"}
    preferences = PlaybackService.provider_preferences(provider_keys)
    providers = []
    for spec in INDEXED_EMBED_PROVIDER_SPECS:
        key = spec.key
        label = spec.display_name
        rows = rows_by_provider.get(key, [])
        configured, configuration_reason = _configured_embed_provider(key)
        preference_enabled = bool(preferences[key]["enabled"])
        enabled_mapping_count = sum(1 for row in rows if row.enabled)
        authorized_enabled_mapping_count = sum(
            1
            for row in rows
            if row.enabled
            and row.authorization_status in AUTHORIZED_EMBED_AUTHORIZATION_STATUSES
        )
        providers.append(
            {
                "provider": key,
                "label": label,
                "configured": configured,
                "configuration_reason": configuration_reason,
                "preference_enabled": preference_enabled,
                "mapping_count": len(rows),
                "enabled_mapping_count": enabled_mapping_count,
                "authorized_enabled_mapping_count": authorized_enabled_mapping_count,
                "ready": configured
                and preference_enabled
                and authorized_enabled_mapping_count > 0,
            }
        )

    vidsrc_configured = bool(current_app.config.get("DRAGON_VIDSRC_ENABLED", False))
    vidsrc_reason = ""
    if not vidsrc_configured:
        vidsrc_reason = "disabled_in_config"
    else:
        base_url = str(current_app.config.get("DRAGON_VIDSRC_EMBED_URL", "")).strip()
        parsed = urlsplit(base_url)
        try:
            port = parsed.port
        except ValueError:
            port = None
            invalid_port = True
        else:
            invalid_port = False
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or invalid_port
            or port == 0
        ):
            vidsrc_configured = False
            vidsrc_reason = "invalid_or_missing_embed_template"
    identity_ready = bool(identity.imdb_id or identity.tmdb_id)
    vidsrc_preference_enabled = bool(preferences["vidsrc"]["enabled"])
    providers.append(
        {
            "provider": "vidsrc",
            "label": "VidSrc",
            "configured": vidsrc_configured,
            "configuration_reason": vidsrc_reason,
            "preference_enabled": vidsrc_preference_enabled,
            "identity_ready": identity_ready,
            "ready": vidsrc_configured and vidsrc_preference_enabled and identity_ready,
        }
    )
    response = jsonify(
        {
            "ok": True,
            "movie_id": movie_id,
            "scope_key": identity.scope_key,
            "providers": providers,
        }
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.get("/movie/<movie_id>/sources/<source_id>/embed")
@login_required
def indexed_embed_source(movie_id: str, source_id: str):
    _require_playback()
    context = get_playback_context(movie_id)
    if context is None:
        abort(404)
    source = db.session.scalar(
        db.select(PlaybackSource).where(
            PlaybackSource.id == source_id,
            PlaybackSource.movie_id == movie_id,
            PlaybackSource.kind == "embed",
            PlaybackSource.source_type == "known_embed",
            PlaybackSource.enabled.is_(True),
            PlaybackSource.authorization_status.in_(AUTHORIZED_EMBED_AUTHORIZATION_STATUSES),
        )
    )
    if source is None:
        abort(404)
    season = _optional_positive_int(request.args.get("season"))
    episode = _optional_positive_int(request.args.get("episode"))
    try:
        identity = PlaybackIdentity.from_context(context, season=season, episode=episode)
    except ValueError as exc:
        return _playback_source_error(str(exc), code="invalid_playback_scope", status=400)
    if identity.scope_key != source.scope_key:
        abort(404)
    provider = _provider_registry().get(source.provider)
    if provider is None or not _provider_is_enabled(source.provider):
        return _playback_source_error(
            "The selected provider is not enabled.", code="provider_disabled", status=409
        )
    try:
        resolved = provider.resolve(identity, source=source)
    except ValueError as exc:
        return _playback_source_error(str(exc), code="source_unavailable", status=409)
    availability = ProviderAvailabilityService.revalidate_if_stale(
        source,
        identity=identity,
        provider=provider,
    )
    if availability.status == "UNAVAILABLE":
        return _playback_source_error(
            "The selected source is currently unavailable.",
            code="source_unavailable",
            status=503,
        )
    source_payload = resolved.response_item() | {"source_id": source.id}
    response = jsonify({"ok": True, "source": source_payload})
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.post("/movie/<movie_id>/sources/<source_id>/selected")
@login_required
def mark_source_selected(movie_id: str, source_id: str):
    _require_playback()
    if get_playback_context(movie_id) is None:
        abort(404)
    source = db.session.scalar(
        db.select(PlaybackSource).where(
            PlaybackSource.id == source_id,
            PlaybackSource.movie_id == movie_id,
            PlaybackSource.enabled.is_(True),
        )
    )
    if source is None:
        abort(404)
    PlaybackService.mark_source_selected(source)
    response = jsonify({"ok": True})
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.post("/movie/<movie_id>/sources/indexed")
@login_required
def add_indexed_embed_source(movie_id: str):
    _require_playback()
    context = get_playback_context(movie_id)
    if context is None:
        abort(404)
    provider_key = str(request.form.get("provider") or "").strip().lower()
    provider = _provider_registry().get(provider_key)
    if provider is None or provider_key == "vidsrc" or not _provider_is_enabled(provider_key):
        abort(404)
    try:
        season = _optional_positive_int(request.form.get("season"))
        episode = _optional_positive_int(request.form.get("episode"))
        if (season is None) != (episode is None):
            raise ValueError("TV playback requires both a season and an episode.")
        if context["media_type"] == "tv" and (
            season is None
            or episode is None
            or not tv_episode_exists(movie_id, season=season, episode=episode)
        ):
            raise ValueError("Choose a valid TV season and episode.")
        if context["media_type"] != "tv" and (season is not None or episode is not None):
            raise ValueError("Movie mappings cannot use a TV episode scope.")
        identity = PlaybackIdentity.from_context(context, season=season, episode=episode)
        provider_asset_id = str(request.form.get("provider_asset_id") or "").strip()
        provider.resolve(identity, source=SimpleNamespace(provider_asset_id=provider_asset_id))
        subtitle_languages = [
            value.strip().lower()
            for value in str(request.form.get("subtitle_languages") or "").split(",")
            if value.strip()
        ]
        PlaybackService.upsert_indexed_embed_source(
            movie_id=movie_id,
            provider=provider_key,
            provider_asset_id=provider_asset_id,
            label=str(request.form.get("label") or "").strip(),
            season=season,
            episode=episode,
            language=str(request.form.get("language") or "").strip().lower(),
            subtitle_languages=subtitle_languages,
            quality=str(request.form.get("quality") or "").strip(),
            provenance={
                "origin": "manual_authorized_import",
                "entered_by": str(current_user.get_id()),
            },
        )
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Authorized embed mapping saved.", "success")
    return redirect(request.referrer or url_for("movies.detail", movie_id=movie_id))


@bp.post("/catalog/imports")
@login_required
def import_catalog():
    _require_playback()
    try:
        if request.files.get("catalog") is not None:
            uploaded = request.files["catalog"]
            filename = Path(uploaded.filename or "").name
            source_name = str(request.form.get("source_name") or filename or "authorized catalog")
            payload = uploaded.read()
            if filename.lower().endswith(".csv"):
                rows = parse_catalog_csv(payload)
                import_method = "csv"
            elif filename.lower().endswith(".json"):
                rows = parse_catalog_json(payload)
                import_method = "json"
            else:
                raise CatalogImportError("Catalog upload must be a .csv or .json file.")
        else:
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                raise CatalogImportError("Provide a JSON catalog object or a CSV/JSON file upload.")
            rows = payload.get("rows")
            if not isinstance(rows, list):
                raise CatalogImportError("Catalog JSON must include a rows list.")
            source_name = str(payload.get("source_name") or "authorized catalog")
            filename = str(payload.get("filename") or "")
            rows = parse_catalog_json(json.dumps({"rows": rows}))
            import_method = "json"
        batch = CatalogImportService.import_rows(
            rows,
            import_method=import_method,
            source_name=source_name,
            filename=filename,
        )
    except CatalogImportError as exc:
        return _playback_source_error(str(exc), code="catalog_import_invalid", status=400)
    response = jsonify({"ok": True, "batch": import_batch_report(batch)})
    response.status_code = 201
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.get("/catalog/imports/<batch_id>")
@login_required
def catalog_import_report(batch_id: str):
    _require_playback()
    batch = db.session.get(ImportBatch, batch_id)
    if batch is None:
        abort(404)
    response = jsonify({"ok": True, "batch": import_batch_report(batch)})
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _playback_source_error(message: str, *, code: str, status: int):
    response = jsonify(
        {
            "ok": False,
            "error": {
                "code": code,
                "message": message,
            },
        }
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response, status


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
        f"v2:{provider_name}:{file_format}:{path}:{member_name}:{season or ''}:"
        f"{episode or ''}:{episode_title.casefold()}"
    )
    cache = current_app.extensions.setdefault("dragon_subtitle_cache", {})
    webvtt = cache.get(cache_key)
    if webvtt is None:
        disk_cache = (
            None if current_app.config.get("TESTING") else _subtitle_disk_cache_path(cache_key)
        )
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
                "transcode_url": url_for("playback.local_transcode", session_id=session["id"]),
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
                "transcode_url": url_for("playback.local_transcode", session_id=session_id),
            },
        }
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.get("/runtime/<session_id>/transcode")
@login_required
def local_transcode(session_id: str):
    _require_local_player()
    manager = _runtime_manager()
    user_id = str(current_user.get_id())
    try:
        status = manager.status(session_id, user_id=user_id)
    except PlaybackRuntimeError as exc:
        return jsonify({"ok": False, "error": {"message": str(exc)}}), 404
    stream_url = str(status.get("stream_url") or "").strip()
    if status.get("state") != "ready" or not stream_url:
        return jsonify({"ok": False, "error": {"message": "Local stream is not ready yet."}}), 409
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
    local_path = manager.transcode_path(session_id, user_id=user_id)

    def mark_failed(message: str) -> None:
        manager.fail(session_id, user_id=user_id, message=message)

    return transcode_stream(
        local_path or stream_url,
        allow_private=local_path is None,
        input_headers={"Origin": origin} if local_path is None else None,
        start_seconds=start_seconds,
        on_failure=mark_failed,
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
