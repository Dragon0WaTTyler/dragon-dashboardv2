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
from flask_login import login_required

from app.shared.operations import OperationService

from .control_center import (
    SECTION_MAP,
    build_control_center,
    build_section_state,
    feature_enabled,
    home_block_position,
    home_block_visible,
    home_layout,
    playback_manager,
    preference_store,
    section_visible,
)

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.app_context_processor
def control_center_preferences():
    return {
        "dragon_feature": feature_enabled,
        "dragon_section_visible": section_visible,
        "dragon_home_layout": home_layout,
        "dragon_home_block_visible": home_block_visible,
        "dragon_home_block_position": home_block_position,
        "dragon_preferences": preference_store().read,
    }


@bp.get("")
@login_required
def index():
    return render_template(
        "admin/index.html",
        active_module="more",
        control_center=build_control_center(),
    )


@bp.get("/general")
@login_required
def general_settings():
    return render_template("admin/general.html", active_module="more")


@bp.get("/home")
@login_required
def home_settings():
    return render_template("admin/home.html", active_module="more")


@bp.get("/advanced")
@login_required
def advanced_settings():
    return render_template(
        "admin/advanced.html",
        active_module="more",
        operations=OperationService.list_recent(limit=8),
    )


@bp.get("/sections/<section_key>")
@login_required
def section_detail(section_key: str):
    section = SECTION_MAP.get(section_key)
    if section is None:
        abort(404)
    context = {}
    if section_key == "mytv":
        from app.mytv.source_manager import (
            REFRESH_INTERVALS as TV_REFRESH_INTERVALS,
        )
        from app.mytv.source_manager import (
            SOURCE_TYPES,
            TVSourceManager,
        )

        categories = TVSourceManager.list_categories()
        category_page_size = 100
        category_pages = max(1, (len(categories) + category_page_size - 1) // category_page_size)
        category_page = min(max(request.args.get("category_page", 1, type=int), 1), category_pages)
        category_start = (category_page - 1) * category_page_size
        context.update(
            tv_sources=TVSourceManager.list_sources(),
            tv_categories=categories[category_start : category_start + category_page_size],
            tv_category_options=categories,
            tv_category_total=len(categories),
            tv_category_page=category_page,
            tv_category_pages=category_pages,
            tv_source_types=SOURCE_TYPES,
            tv_refresh_intervals=sorted(TV_REFRESH_INTERVALS),
        )
    elif section_key == "reading":
        from app.reading.source_manager import (
            ARTICLE_LIMITS,
            LANGUAGES,
            ReadingSourceManager,
        )
        from app.reading.source_manager import (
            REFRESH_INTERVALS as READING_REFRESH_INTERVALS,
        )

        context.update(
            reading_sources=ReadingSourceManager.list_sources(),
            reading_categories=ReadingSourceManager.list_categories(),
            reading_languages=sorted(LANGUAGES),
            reading_refresh_intervals=sorted(READING_REFRESH_INTERVALS),
            reading_article_limits=sorted(ARTICLE_LIMITS),
        )
    return render_template(
        "admin/section_detail.html",
        active_module="more",
        section_state=build_section_state(section),
        **context,
    )


@bp.post("/sections/<section_key>/preferences")
@login_required
def update_section_preferences(section_key: str):
    if section_key not in SECTION_MAP:
        abort(404)
    # Keep select values as strings. Checkbox absence is handled by PreferenceStore,
    # while coercing every form value to a boolean silently reset default view/sort.
    values = request.form.to_dict()
    saved = preference_store().update(section_key, values)
    if section_key == "reading":
        from app.extensions import db
        from app.reading.services import ReadingService

        reading = saved["sections"]["reading"]
        ReadingService.trim_by_age(
            days=reading["retention_days"],
            protect_saved=reading["never_delete_saved"],
        )
        db.session.commit()
    flash(f"{SECTION_MAP[section_key].label} preferences saved.", "success")
    return redirect(url_for("admin.section_detail", section_key=section_key))


@bp.post("/general/preferences")
@login_required
def update_general_preferences():
    preference_store().update_general(request.form)
    flash("General settings saved.", "success")
    return redirect(url_for("admin.general_settings"))


@bp.post("/home/preferences")
@login_required
def update_home_preferences():
    preference_store().update_home(request.form)
    flash("Home layout saved.", "success")
    return redirect(url_for("admin.home_settings"))


@bp.post("/sections/<section_key>/reset")
@login_required
def reset_section_preferences(section_key: str):
    if section_key not in SECTION_MAP:
        abort(404)
    preference_store().reset_section(section_key)
    flash(f"{SECTION_MAP[section_key].label} settings restored to defaults.", "success")
    return redirect(url_for("admin.section_detail", section_key=section_key))


@bp.post("/sections/movies/playback-cache/clear")
@login_required
def clear_playback_cache():
    result = playback_manager().clear_inactive_cache()
    removed_mb = result["removed_bytes"] / 1024 / 1024
    flash(f"Cleared {removed_mb:.1f} MB from inactive playback cache.", "success")
    return redirect(url_for("admin.section_detail", section_key="movies"))


@bp.post("/sections/movies/discovery-cache/clear")
@login_required
def clear_movies_discovery_cache():
    disposable_keys = (
        "dragon_movies_discovery_rails",
        "dragon_movies_browse_cache",
        "dragon_tmdb_alternate_title_cache",
    )
    removed = sum(1 for key in disposable_keys if current_app.extensions.pop(key, None) is not None)
    from app.movies.external_library import tmdb_catalog_provider

    clear_aliases = getattr(tmdb_catalog_provider(), "clear_alternate_title_cache", None)
    if callable(clear_aliases):
        removed += int(clear_aliases())
    flash(
        f"Cleared {removed} disposable Movies cache {'entry' if removed == 1 else 'entries'}. "
        "Your library, lists, progress, and sources were not changed.",
        "success",
    )
    return redirect(url_for("admin.section_detail", section_key="movies"))


def _tv_source(source_id: int):
    from app.extensions import db
    from app.mytv.models import TVSource

    source = db.session.get(TVSource, source_id)
    if source is None:
        abort(404)
    return source


@bp.post("/sections/mytv/sources")
@login_required
def create_tv_source():
    from app.mytv.source_manager import TVSourceManager, TVSourceValidationError

    manager = TVSourceManager()
    try:
        source = manager.create(request.form, request.files.get("local_file"))
        if request.form.get("submit_action") == "import":
            result = manager.sync(source)
            flash(
                f"TV source saved and imported: {result['channels']:,} channels "
                f"from {result['files']} file(s).",
                "success",
            )
        elif request.form.get("submit_action") == "test":
            result = manager.test(source)
            flash(f"Source added and tested: {result['files']} M3U file(s) found.", "success")
        else:
            flash("TV source saved. Use Import / update to load its channels.", "success")
    except TVSourceValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.section_detail", section_key="mytv") + "#source-manager")


@bp.post("/sections/mytv/sources/test-draft")
@login_required
def test_tv_source_draft():
    from app.mytv.source_manager import TVSourceManager, TVSourceValidationError

    try:
        result = TVSourceManager().test_configuration(
            request.form, request.files.get("local_file")
        )
        return jsonify(ok=True, message=f"Connection healthy: {result['files']} M3U file(s) found.")
    except TVSourceValidationError as exc:
        return jsonify(ok=False, message=str(exc)), 400


@bp.post("/sections/mytv/sources/<int:source_id>/update")
@login_required
def update_tv_source(source_id: int):
    from app.mytv.source_manager import TVSourceManager, TVSourceValidationError

    manager = TVSourceManager()
    try:
        source = manager.update(
            _tv_source(source_id), request.form, request.files.get("local_file")
        )
        if request.form.get("submit_action") == "import":
            result = manager.sync(source)
            flash(
                f"TV source saved and imported: {result['channels']:,} channels "
                f"from {result['files']} file(s).",
                "success",
            )
        elif request.form.get("submit_action") == "test":
            manager.test(source)
            flash("TV source saved and connection tested.", "success")
        else:
            flash("TV source settings saved.", "success")
    except TVSourceValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.section_detail", section_key="mytv") + "#source-manager")


@bp.post("/sections/mytv/builtin-source")
@login_required
def update_builtin_tv_source():
    from app.mytv.source_manager import TVSourceManager, TVSourceValidationError

    manager = TVSourceManager()
    try:
        source_id = request.form.get("source_id", type=int)
        source = manager.update_builtin(_tv_source(source_id), request.form)
        if request.form.get("submit_action") == "import":
            result = manager.sync(source)
            flash(
                f"Primary TV catalogue saved and updated: {result['channels']:,} channels "
                f"from {result['files']} file(s).",
                "success",
            )
        else:
            flash("Primary TV catalogue settings saved.", "success")
    except TVSourceValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.section_detail", section_key="mytv") + "#source-manager")


@bp.post("/sections/mytv/sources/<int:source_id>/<action>")
@login_required
def run_tv_source_action(source_id: int, action: str):
    from app.mytv.source_manager import TVSourceManager, TVSourceValidationError

    manager = TVSourceManager()
    source = _tv_source(source_id)
    try:
        if action == "test":
            result = manager.test(source)
            flash(f"Connection healthy: {result['files']} M3U file(s) found.", "success")
        elif action == "refresh":
            result = manager.sync(source)
            flash(
                f"TV source refreshed: {result['channels']:,} channels "
                f"from {result['files']} file(s).",
                "success",
            )
        elif action == "toggle":
            enabled = manager.toggle(source)
            flash("TV source enabled." if enabled else "TV source paused.", "success")
        else:
            abort(404)
    except TVSourceValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.section_detail", section_key="mytv") + "#source-manager")


@bp.post("/sections/mytv/sources/<int:source_id>/delete")
@login_required
def delete_tv_source(source_id: int):
    from app.mytv.source_manager import TVSourceManager, TVSourceValidationError

    if request.form.get("confirmed") != "yes":
        flash("Confirm exactly what should happen to imported channels.", "warning")
        return redirect(url_for("admin.section_detail", section_key="mytv") + "#source-manager")
    try:
        TVSourceManager.delete(
            _tv_source(source_id), keep_data=request.form.get("data_action") == "keep"
        )
        flash("TV source removed with the selected data policy.", "success")
    except TVSourceValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.section_detail", section_key="mytv") + "#source-manager")


@bp.post("/sections/mytv/categories/<int:theme_id>")
@login_required
def update_tv_category(theme_id: int):
    from app.extensions import db
    from app.mytv.models import TVTheme
    from app.mytv.source_manager import TVSourceManager, TVSourceValidationError

    theme = db.session.get(TVTheme, theme_id)
    if theme is None:
        abort(404)
    try:
        TVSourceManager.update_category(theme, request.form)
        flash("TV category updated.", "success")
    except TVSourceValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.section_detail", section_key="mytv") + "#category-manager")


@bp.post("/sections/mytv/categories/<int:theme_id>/<action>")
@login_required
def run_tv_category_action(theme_id: int, action: str):
    from app.extensions import db
    from app.mytv.models import TVTheme
    from app.mytv.source_manager import TVSourceManager, TVSourceValidationError

    theme = db.session.get(TVTheme, theme_id)
    if theme is None:
        abort(404)
    try:
        if action in {"up", "down"}:
            TVSourceManager.move_category(theme, action)
            flash("TV category order updated.", "success")
        elif action == "merge":
            target_id = request.form.get("target_id", type=int)
            target = db.session.get(TVTheme, target_id) if target_id else None
            if target is None:
                target_name = str(request.form.get("target_name") or "").strip()
                target = db.session.scalar(
                    db.select(TVTheme).where(
                        TVTheme.name == target_name,
                        TVTheme.id != theme.id,
                    )
                )
            if target is None:
                raise TVSourceValidationError("Choose a valid merge destination.")
            TVSourceManager.merge_category(theme, target)
            flash("TV categories merged.", "success")
        else:
            abort(404)
    except TVSourceValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.section_detail", section_key="mytv") + "#category-manager")


def _reading_source(source_id: str):
    from app.extensions import db
    from app.reading.models import ReadingSource

    source = db.session.get(ReadingSource, source_id)
    if source is None:
        abort(404)
    return source


@bp.post("/sections/reading/sources")
@login_required
def create_reading_source():
    from app.reading.source_manager import ReadingSourceManager, ReadingSourceValidationError

    try:
        source = ReadingSourceManager.create(request.form)
        if request.form.get("submit_action") == "test":
            client = current_app.extensions.get("dragon_feed_client")
            if client is None:
                raise ReadingSourceValidationError("RSS testing is unavailable.")
            count = ReadingSourceManager.test(source, client)
            flash(f"RSS source added and tested: {count} entries found.", "success")
        else:
            flash("RSS source added. Test or refresh it when you are ready.", "success")
    except ReadingSourceValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.section_detail", section_key="reading") + "#source-manager")


@bp.post("/sections/reading/sources/test-draft")
@login_required
def test_reading_source_draft():
    from app.reading.source_manager import ReadingSourceManager, ReadingSourceValidationError

    client = current_app.extensions.get("dragon_feed_client")
    if client is None:
        return jsonify(ok=False, message="RSS testing is unavailable."), 503
    try:
        count = ReadingSourceManager.test_configuration(request.form, client)
        return jsonify(ok=True, message=f"Connection healthy: {count} entries found.")
    except ReadingSourceValidationError as exc:
        return jsonify(ok=False, message=str(exc)), 400


@bp.post("/sections/reading/sources/<source_id>/update")
@login_required
def update_reading_source(source_id: str):
    from app.reading.source_manager import ReadingSourceManager, ReadingSourceValidationError

    try:
        source = ReadingSourceManager.update(_reading_source(source_id), request.form)
        if request.form.get("submit_action") == "test":
            client = current_app.extensions.get("dragon_feed_client")
            if client is None:
                raise ReadingSourceValidationError("RSS testing is unavailable.")
            ReadingSourceManager.test(source, client)
            flash("RSS source saved and tested.", "success")
        else:
            flash("RSS source settings saved.", "success")
    except ReadingSourceValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.section_detail", section_key="reading") + "#source-manager")


@bp.post("/sections/reading/sources/<source_id>/<action>")
@login_required
def run_reading_source_action(source_id: str, action: str):
    from app.reading.source_manager import ReadingSourceManager, ReadingSourceValidationError

    source = _reading_source(source_id)
    client = current_app.extensions.get("dragon_feed_client")
    try:
        if action == "toggle":
            enabled = ReadingSourceManager.toggle(source)
            flash("RSS source enabled." if enabled else "RSS source paused.", "success")
        elif action == "test":
            if client is None:
                raise ReadingSourceValidationError("RSS testing is unavailable.")
            count = ReadingSourceManager.test(source, client)
            flash(f"RSS connection healthy: {count} entries found.", "success")
        elif action == "refresh":
            if client is None:
                raise ReadingSourceValidationError("RSS synchronization is unavailable.")
            result = ReadingSourceManager.refresh(source, client)
            flash(
                f"RSS refreshed: {result['created']} new and {result['updated']} updated.",
                "success",
            )
        else:
            abort(404)
    except ReadingSourceValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.section_detail", section_key="reading") + "#source-manager")


@bp.post("/sections/reading/sources/<source_id>/delete")
@login_required
def delete_reading_source(source_id: str):
    from app.reading.source_manager import ReadingSourceManager

    if request.form.get("confirmed") != "yes":
        flash("Confirm exactly what should happen to cached articles.", "warning")
        return redirect(url_for("admin.section_detail", section_key="reading") + "#source-manager")
    ReadingSourceManager.delete(
        _reading_source(source_id), keep_articles=request.form.get("data_action") == "keep"
    )
    flash("RSS source removed with the selected article policy.", "success")
    return redirect(url_for("admin.section_detail", section_key="reading") + "#source-manager")


@bp.post("/sections/reading/categories")
@login_required
def update_reading_category():
    from app.reading.source_manager import ReadingSourceManager, ReadingSourceValidationError

    try:
        ReadingSourceManager.update_category(str(request.form.get("current") or ""), request.form)
        flash("News category updated.", "success")
    except ReadingSourceValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.section_detail", section_key="reading") + "#category-manager")


def _safe_return_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/admin"):
        return None
    return value


@bp.post("/run")
@login_required
def run_operation():
    from app.shared.refresh import OperationCoordinator

    kind = str(request.form.get("kind") or "")
    domain = str(request.form.get("domain") or "")
    if kind == "sync" and domain == "all" and request.form.get("confirmed") != "yes":
        flash("Confirm the global synchronization before running it.", "warning")
        return redirect(_safe_return_url(request.form.get("next")) or url_for("admin.index"))
    try:
        operation = OperationCoordinator.run(kind=kind, domain=domain)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(_safe_return_url(request.form.get("next")) or url_for("admin.index"))
    flash("Operation finished with a local report.", "success")
    return redirect(
        _safe_return_url(request.form.get("next"))
        or url_for("admin.operation_detail", operation_id=operation.id)
    )


@bp.get("/design-system")
@login_required
def design_system():
    return render_template("admin/design_system.html", active_module="more")


@bp.get("/operations")
@login_required
def operations():
    return render_template(
        "admin/operations.html",
        active_module="more",
        operations=OperationService.list_recent(limit=50),
    )


@bp.get("/operations/<operation_id>")
@login_required
def operation_detail(operation_id: str):
    operation = OperationService.get(operation_id)
    if operation is None:
        abort(404)
    return render_template(
        "admin/operation_detail.html",
        active_module="more",
        operation=operation,
    )
