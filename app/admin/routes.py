from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.shared.operations import OperationService

from .control_center import (
    SECTION_MAP,
    build_control_center,
    build_section_state,
    feature_enabled,
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
    }


@bp.get("")
@login_required
def index():
    return render_template(
        "admin/index.html",
        active_module="more",
        control_center=build_control_center(),
        operations=OperationService.list_recent(limit=8),
    )


@bp.get("/sections/<section_key>")
@login_required
def section_detail(section_key: str):
    section = SECTION_MAP.get(section_key)
    if section is None:
        abort(404)
    return render_template(
        "admin/section_detail.html",
        active_module="more",
        section_state=build_section_state(section),
    )


@bp.post("/sections/<section_key>/preferences")
@login_required
def update_section_preferences(section_key: str):
    if section_key not in SECTION_MAP:
        abort(404)
    values = {key: value == "on" for key, value in request.form.items()}
    preference_store().update(section_key, values)
    flash(f"{SECTION_MAP[section_key].label} preferences saved.", "success")
    return redirect(url_for("admin.section_detail", section_key=section_key))


@bp.post("/sections/movies/playback-cache/clear")
@login_required
def clear_playback_cache():
    result = playback_manager().clear_inactive_cache()
    removed_mb = result["removed_bytes"] / 1024 / 1024
    flash(f"Cleared {removed_mb:.1f} MB from inactive playback cache.", "success")
    return redirect(url_for("admin.section_detail", section_key="movies"))


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
