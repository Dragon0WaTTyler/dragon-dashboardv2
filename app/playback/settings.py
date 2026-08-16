from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.movies.models import Movie
from app.playback.catalog import (
    CatalogImportError,
    CatalogImportService,
    parse_catalog_csv,
    parse_catalog_json,
)
from app.playback.host_library import (
    DoodStreamLibrarySyncService,
    FileLionsLibrarySyncService,
    HostLibrarySyncError,
    LuluStreamLibrarySyncService,
    MixDropLibrarySyncService,
    StreamTapeLibrarySyncService,
    StreamWishLibrarySyncService,
    build_doodstream_account_client,
    build_filelions_account_client,
    build_lulustream_account_client,
    build_mixdrop_account_client,
    build_streamtape_account_client,
    build_streamwish_account_client,
)
from app.playback.models import ImportBatch, ImportRow, PlaybackSource
from app.playback.providers import (
    ID_CATALOG_EMBED_PROVIDER_SPECS,
    INDEXED_EMBED_PROVIDER_SPECS,
    build_provider_registry_from_config,
)
from app.playback.services import (
    AUTHORIZED_EMBED_AUTHORIZATION_STATUSES,
    INDEXED_EMBED_SOURCE_TYPES,
    PlaybackService,
)

bp = Blueprint("playback_settings", __name__, url_prefix="/settings/playback")

PRODUCTION_CATALOG_PROVIDER_KEYS = ("videotube", "updown", "ok")


def _configured_providers() -> list[dict]:
    registry = build_provider_registry_from_config(current_app.config)
    registered_provider_keys = registry.keys()
    provider_keys: list[str] = []
    if current_app.config.get("DRAGON_PLAYBACK_ENABLED") and current_app.config.get(
        "DRAGON_VIDSRC_ENABLED"
    ):
        provider_keys.append("vidsrc")
    if current_app.config.get("DRAGON_PLAYBACK_ENABLED"):
        provider_keys.extend(
            spec.key
            for spec in INDEXED_EMBED_PROVIDER_SPECS
            if spec.key in registered_provider_keys
        )
        provider_keys.extend(
            spec.key
            for spec in ID_CATALOG_EMBED_PROVIDER_SPECS
            if spec.key in registered_provider_keys
        )
    preferences = PlaybackService.provider_preferences(frozenset(provider_keys))
    return [
        {
            "key": key,
            "label": registry.require(key).display_name if key != "vidsrc" else "VidSrc",
            **preferences[key],
        }
        for key in provider_keys
    ]


def _require_playback() -> None:
    if not current_app.config.get("DRAGON_PLAYBACK_ENABLED"):
        abort(404)


def _catalog_provider_readiness() -> list[dict]:
    """Describe local integration readiness without exposing URLs or probing hosts."""
    registry = build_provider_registry_from_config(current_app.config)
    configured_keys = registry.keys()
    preferences = PlaybackService.provider_preferences(
        frozenset(PRODUCTION_CATALOG_PROVIDER_KEYS)
    )
    readiness = []
    for key in PRODUCTION_CATALOG_PROVIDER_KEYS:
        spec = next(spec for spec in INDEXED_EMBED_PROVIDER_SPECS if spec.key == key)
        configured = key in configured_keys
        preference_enabled = bool(preferences[key]["enabled"])
        if not configured:
            status = "Not configured"
        elif not preference_enabled:
            status = "Disabled in provider settings"
        else:
            status = "Ready for activated mappings"
        readiness.append(
            {
                "key": key,
                "label": spec.display_name,
                "configured": configured,
                "preference_enabled": preference_enabled,
                "ready": configured and preference_enabled,
                "status": status,
            }
        )
    return readiness


def _streamwish_library_readiness() -> dict:
    """Expose only local readiness; never make an account API request on GET."""
    configured = bool(current_app.config.get("DRAGON_STREAMWISH_LIBRARY_SYNC_ENABLED"))
    credentials_present = bool(current_app.config.get("DRAGON_STREAMWISH_API_KEY"))
    if not configured:
        status = "Library sync is disabled in configuration"
    elif not credentials_present:
        status = "StreamWish API key is missing from the local secret store"
    else:
        status = "Ready for a manual account-library sync"
    return {
        "configured": configured,
        "credentials_present": credentials_present,
        "ready": configured and credentials_present,
        "status": status,
    }


def _mixdrop_library_readiness() -> dict:
    """Expose only local readiness; never make an account API request on GET."""
    configured = bool(current_app.config.get("DRAGON_MIXDROP_LIBRARY_SYNC_ENABLED"))
    credentials_present = bool(
        current_app.config.get("DRAGON_MIXDROP_API_EMAIL")
        and current_app.config.get("DRAGON_MIXDROP_API_KEY")
    )
    if not configured:
        status = "Library sync is disabled in configuration"
    elif not credentials_present:
        status = "MixDrop API credentials are missing from the local secret store"
    else:
        status = "Ready for a manual account-library sync"
    return {
        "configured": configured,
        "credentials_present": credentials_present,
        "ready": configured and credentials_present,
        "status": status,
    }


def _streamtape_library_readiness() -> dict:
    configured = bool(current_app.config.get("DRAGON_STREAMTAPE_LIBRARY_SYNC_ENABLED"))
    credentials_present = bool(
        current_app.config.get("DRAGON_STREAMTAPE_API_LOGIN")
        and current_app.config.get("DRAGON_STREAMTAPE_API_KEY")
    )
    if not configured:
        status = "Library sync is disabled in configuration"
    elif not credentials_present:
        status = "StreamTape API credentials are missing from the local secret store"
    else:
        status = "Ready for a manual account-library sync"
    return {
        "configured": configured,
        "credentials_present": credentials_present,
        "ready": configured and credentials_present,
        "status": status,
    }


def _filelions_library_readiness() -> dict:
    configured = bool(current_app.config.get("DRAGON_FILELIONS_LIBRARY_SYNC_ENABLED"))
    credentials_present = bool(current_app.config.get("DRAGON_FILELIONS_API_KEY"))
    if not configured:
        status = "Library sync is disabled in configuration"
    elif not credentials_present:
        status = "FileLions API key is missing from the local secret store"
    else:
        status = "Ready for a manual account-library sync"
    return {
        "configured": configured,
        "credentials_present": credentials_present,
        "ready": configured and credentials_present,
        "status": status,
    }


def _doodstream_library_readiness() -> dict:
    configured = bool(current_app.config.get("DRAGON_DOODSTREAM_LIBRARY_SYNC_ENABLED"))
    credentials_present = bool(current_app.config.get("DRAGON_DOODSTREAM_API_KEY"))
    status = (
        "Library sync is disabled in configuration" if not configured
        else "DoodStream API key is missing from the local secret store" if not credentials_present
        else "Ready for a manual account-library sync"
    )
    return {"configured": configured, "credentials_present": credentials_present,
            "ready": configured and credentials_present, "status": status}


def _lulustream_library_readiness() -> dict:
    configured = bool(current_app.config.get("DRAGON_LULUSTREAM_LIBRARY_SYNC_ENABLED"))
    credentials_present = bool(current_app.config.get("DRAGON_LULUSTREAM_API_KEY"))
    status = (
        "Library sync is disabled in configuration" if not configured
        else "LuluStream API key is missing from the local secret store" if not credentials_present
        else "Ready for a manual account-library sync"
    )
    return {"configured": configured, "credentials_present": credentials_present,
            "ready": configured and credentials_present, "status": status}


def _catalog_batch_view(batch: ImportBatch, *, row_limit: int = 100) -> dict:
    """Return an operator-safe, bounded import report for the settings page."""
    rows = list(
        db.session.scalars(
            db.select(ImportRow)
            .where(ImportRow.batch_id == batch.id)
            .order_by(ImportRow.row_number)
            .limit(row_limit)
        )
    )
    movie_ids = {row.matched_movie_id for row in rows if row.matched_movie_id}
    movies = {
        movie.id: movie
        for movie in db.session.scalars(db.select(Movie).where(Movie.id.in_(movie_ids)))
    } if movie_ids else {}
    source_ids = {row.created_playback_source_id for row in rows if row.created_playback_source_id}
    sources = {
        source.id: source
        for source in db.session.scalars(
            db.select(PlaybackSource).where(PlaybackSource.id.in_(source_ids))
        )
    } if source_ids else {}
    return {
        "id": batch.id,
        "source_name": batch.source_name,
        "filename": batch.filename,
        "import_method": batch.import_method,
        "total_rows": batch.total_rows,
        "accepted_rows": batch.accepted_rows,
        "review_rows": batch.review_rows,
        "rejected_rows": batch.rejected_rows,
        "error_rows": batch.error_rows,
        "rows_truncated": batch.total_rows > len(rows),
        "rows": [
            {
                "row_number": row.row_number,
                "match_status": row.match_status,
                "reason": row.reason,
                "provider": row.provider,
                "provider_asset_id": row.provider_asset_id,
                "movie": movies.get(row.matched_movie_id),
                "source": sources.get(row.created_playback_source_id),
            }
            for row in rows
        ],
    }


@bp.get("")
@login_required
def index():
    return render_template(
        "playback/settings.html",
        active_module="more",
        providers=_configured_providers(),
    )


@bp.get("/catalog")
@login_required
def catalog():
    _require_playback()
    batch_id = str(request.args.get("batch") or "").strip()
    selected_batch = db.session.get(ImportBatch, batch_id) if batch_id else None
    if batch_id and selected_batch is None:
        abort(404)
    recent_batches = list(
        db.session.scalars(
            db.select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(10)
        )
    )
    if selected_batch is None and recent_batches:
        selected_batch = recent_batches[0]
    return render_template(
        "playback/catalog.html",
        active_module="more",
        batch=_catalog_batch_view(selected_batch) if selected_batch else None,
        provider_readiness=_catalog_provider_readiness(),
        streamwish_library=_streamwish_library_readiness(),
        mixdrop_library=_mixdrop_library_readiness(),
        streamtape_library=_streamtape_library_readiness(),
        filelions_library=_filelions_library_readiness(),
        doodstream_library=_doodstream_library_readiness(),
        lulustream_library=_lulustream_library_readiness(),
        recent_batches=recent_batches,
    )


@bp.post("/catalog/imports")
@login_required
def import_catalog():
    _require_playback()
    uploaded = request.files.get("catalog")
    if uploaded is None or not uploaded.filename:
        flash("Choose an authorized CSV or JSON catalog file.", "error")
        return redirect(url_for("playback_settings.catalog"))
    filename = Path(uploaded.filename).name
    source_name = str(request.form.get("source_name") or filename or "authorized catalog")
    try:
        payload = uploaded.read()
        if filename.lower().endswith(".csv"):
            rows = parse_catalog_csv(payload)
            import_method = "csv"
        elif filename.lower().endswith(".json"):
            rows = parse_catalog_json(payload)
            import_method = "json"
        else:
            raise CatalogImportError("Catalog upload must be a .csv or .json file.")
        batch = CatalogImportService.import_rows(
            rows,
            import_method=import_method,
            source_name=source_name,
            filename=filename,
        )
    except CatalogImportError as exc:
        flash(str(exc), "error")
        return redirect(url_for("playback_settings.catalog"))
    flash(
        f"Catalog imported: {batch.accepted_rows} accepted, {batch.review_rows} for review, "
        f"{batch.rejected_rows + batch.error_rows} not imported.",
        "success",
    )
    return redirect(url_for("playback_settings.catalog", batch=batch.id))


@bp.post("/catalog/streamwish/sync")
@login_required
def sync_streamwish_library():
    _require_playback()
    try:
        client = current_app.extensions.get("dragon_streamwish_account_client")
        if client is None:
            client = build_streamwish_account_client(current_app.config)
        result = StreamWishLibrarySyncService.sync(client)
    except HostLibrarySyncError as exc:
        flash(str(exc), "error")
        return redirect(url_for("playback_settings.catalog"))
    flash(
        "StreamWish library synced: "
        f"{result.assets_cached} valid assets cached; {result.batch.accepted_rows} mappings await review.",
        "success",
    )
    return redirect(url_for("playback_settings.catalog", batch=result.batch.id))


@bp.post("/catalog/mixdrop/sync")
@login_required
def sync_mixdrop_library():
    _require_playback()
    try:
        client = current_app.extensions.get("dragon_mixdrop_account_client")
        if client is None:
            client = build_mixdrop_account_client(current_app.config)
        result = MixDropLibrarySyncService.sync(client)
    except HostLibrarySyncError as exc:
        flash(str(exc), "error")
        return redirect(url_for("playback_settings.catalog"))
    flash(
        "MixDrop library synced: "
        f"{result.assets_cached} valid assets cached; {result.batch.accepted_rows} mappings await review.",
        "success",
    )
    return redirect(url_for("playback_settings.catalog", batch=result.batch.id))


@bp.post("/catalog/streamtape/sync")
@login_required
def sync_streamtape_library():
    _require_playback()
    try:
        client = current_app.extensions.get("dragon_streamtape_account_client")
        if client is None:
            client = build_streamtape_account_client(current_app.config)
        result = StreamTapeLibrarySyncService.sync(client)
    except HostLibrarySyncError as exc:
        flash(str(exc), "error")
        return redirect(url_for("playback_settings.catalog"))
    flash(
        "StreamTape library synced: "
        f"{result.assets_cached} valid assets cached; {result.batch.accepted_rows} mappings await review.",
        "success",
    )
    return redirect(url_for("playback_settings.catalog", batch=result.batch.id))


@bp.post("/catalog/filelions/sync")
@login_required
def sync_filelions_library():
    _require_playback()
    try:
        client = current_app.extensions.get("dragon_filelions_account_client")
        if client is None:
            client = build_filelions_account_client(current_app.config)
        result = FileLionsLibrarySyncService.sync(client)
    except HostLibrarySyncError as exc:
        flash(str(exc), "error")
        return redirect(url_for("playback_settings.catalog"))
    flash(
        "FileLions library synced: "
        f"{result.assets_cached} valid assets cached; {result.batch.accepted_rows} mappings await review.",
        "success",
    )
    return redirect(url_for("playback_settings.catalog", batch=result.batch.id))


@bp.post("/catalog/doodstream/sync")
@login_required
def sync_doodstream_library():
    _require_playback()
    try:
        client = current_app.extensions.get("dragon_doodstream_account_client")
        if client is None:
            client = build_doodstream_account_client(current_app.config)
        result = DoodStreamLibrarySyncService.sync(client)
    except HostLibrarySyncError as exc:
        flash(str(exc), "error")
        return redirect(url_for("playback_settings.catalog"))
    flash(
        "DoodStream library synced: "
        f"{result.assets_cached} valid assets cached; {result.batch.accepted_rows} mappings await review.",
        "success",
    )
    return redirect(url_for("playback_settings.catalog", batch=result.batch.id))


@bp.post("/catalog/lulustream/sync")
@login_required
def sync_lulustream_library():
    _require_playback()
    try:
        client = current_app.extensions.get("dragon_lulustream_account_client")
        if client is None:
            client = build_lulustream_account_client(current_app.config)
        result = LuluStreamLibrarySyncService.sync(client)
    except HostLibrarySyncError as exc:
        flash(str(exc), "error")
        return redirect(url_for("playback_settings.catalog"))
    flash(
        "LuluStream library synced: "
        f"{result.assets_cached} valid assets cached; {result.batch.accepted_rows} mappings await review.",
        "success",
    )
    return redirect(url_for("playback_settings.catalog", batch=result.batch.id))


@bp.post("/catalog/sources/<source_id>/enabled")
@login_required
def set_catalog_source_enabled(source_id: str):
    _require_playback()
    source = db.session.scalar(
        db.select(PlaybackSource).where(
            PlaybackSource.id == source_id,
            PlaybackSource.kind == "embed",
            PlaybackSource.source_type.in_(INDEXED_EMBED_SOURCE_TYPES),
            PlaybackSource.authorization_status.in_(AUTHORIZED_EMBED_AUTHORIZATION_STATUSES),
        )
    )
    if source is None:
        abort(404)
    source.enabled = str(request.form.get("enabled") or "").strip().lower() in {
        "true",
        "1",
        "on",
    }
    if not source.enabled:
        source.selected = False
    db.session.commit()
    action = "activated" if source.enabled else "disabled"
    flash(f"{source.provider.title()} mapping {action}.", "success")
    batch_id = str(request.form.get("batch_id") or "").strip()
    destination = (
        url_for("playback_settings.catalog", batch=batch_id)
        if batch_id
        else url_for("playback_settings.catalog")
    )
    return redirect(destination)


@bp.post("/providers/<provider>")
@login_required
def update_provider(provider: str):
    configured = {item["key"] for item in _configured_providers()}
    if provider not in configured:
        abort(404)
    try:
        priority = int(str(request.form.get("priority") or "100"))
    except ValueError:
        flash("Provider priority must be a whole number.", "error")
        return redirect(url_for("playback_settings.index"))
    PlaybackService.save_provider_preference(
        provider=provider,
        enabled=request.form.get("enabled") == "on",
        priority=priority,
        background_checks=request.form.get("background_checks") == "on",
    )
    flash("Playback provider preference saved.", "success")
    return redirect(url_for("playback_settings.index"))
