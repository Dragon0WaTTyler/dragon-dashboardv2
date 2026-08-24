from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required

from app.extensions import db
from app.personal_tv.models import PreparedTVProgram, TVSession
from app.personal_tv.programming import (
    DISCOVERY_LEVELS,
    ProgrammingRequest,
    normalise_terms,
    parse_intent,
)
from app.personal_tv.providers import YouTubeCandidateProvider
from app.personal_tv.services import PersonalTVService
from app.youtube.grouping import selected_theme

bp = Blueprint("personal_tv", __name__, url_prefix="/my-tv")
_DURATIONS = {30, 60, 90, 120}


def _list(payload: dict, key: str) -> tuple[str, ...]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
        raise ValueError(f"{key.replace('_', ' ').capitalize()} must be a list.")
    return normalise_terms(value)


def _groups(payload: dict) -> tuple[str, ...]:
    value = _list(payload, "groups")
    return normalise_terms([theme for item in value if (theme := selected_theme(item))])


def _request_from_payload(payload: dict) -> ProgrammingRequest:
    try:
        duration = int(payload.get("duration_minutes", 60))
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose a valid session duration.") from exc
    if duration not in _DURATIONS:
        raise ValueError("Choose 30, 60, 90, or 120 minutes.")
    discovery = str(payload.get("discovery_level", "balanced")).casefold()
    if discovery not in DISCOVERY_LEVELS:
        raise ValueError("Discovery must be low, balanced, or high.")
    return ProgrammingRequest(
        duration_minutes=duration,
        groups=_groups(payload),
        avoid_watched=bool(payload.get("avoid_watched", True)),
        no_shorts=bool(payload.get("no_shorts", True)),
        topics=_list(payload, "topics"),
        formats=_list(payload, "formats"),
        languages=_list(payload, "languages"),
        mood=str(payload.get("mood", ""))[:80],
        goal=str(payload.get("goal", ""))[:80],
        discovery_level=discovery,
        allow_live=bool(payload.get("allow_live", False)),
    )


def _session_or_404(session_id: str):
    session = db.session.get(TVSession, session_id)
    if session is None:
        return None, (jsonify({"ok": False, "error": "Session not found."}), 404)
    return session, None


@bp.get("")
@login_required
def index():
    return render_template("personal_tv/index.html", active_module="personal_tv")


@bp.get("/api/bootstrap")
@login_required
def bootstrap():
    return jsonify(
        {
            "ok": True,
            "preferences": PersonalTVService.preferences_payload(),
            "groups": YouTubeCandidateProvider.groups(),
            "active_session": PersonalTVService.session_payload(PersonalTVService.active_session()),
            "profile": PersonalTVService.viewer_profile_payload(),
        }
    )


@bp.post("/api/catalogue/deepen")
@login_required
def deepen_catalogue():
    groups = _groups(request.get_json(silent=True) or {})
    if not groups:
        return jsonify({"ok": False, "error": "Choose at least one collection first."}), 400
    result = PersonalTVService.deepen_collections(groups)
    return jsonify(
        {
            "ok": True,
            "result": result,
            "groups": YouTubeCandidateProvider.groups(),
        }
    )


@bp.route("/api/preferences", methods=["GET", "PATCH"])
@login_required
def preferences():
    if request.method == "GET":
        return jsonify({"ok": True, "preferences": PersonalTVService.preferences_payload()})
    try:
        record = PersonalTVService.update_preferences(request.get_json(silent=True) or {})
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "preferences": PersonalTVService.preferences_payload(record)})


@bp.post("/api/intent")
@login_required
def intent():
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    if not text:
        return jsonify({"ok": False, "error": "Describe the session you want."}), 400
    request_model = parse_intent(
        text,
        default_duration=PersonalTVService.preferences().default_duration_minutes,
    )
    return jsonify({"ok": True, "intent": request_model.as_dict()})


@bp.get("/api/profile")
@login_required
def profile():
    return jsonify({"ok": True, "profile": PersonalTVService.viewer_profile_payload()})


@bp.route("/api/sync-state", methods=["GET", "PUT"])
@login_required
def sync_state():
    if request.method == "GET":
        return jsonify({"ok": True, "state": PersonalTVService.semantic_state()})
    try:
        state = PersonalTVService.merge_semantic_state(
            (request.get_json(silent=True) or {}).get("state", {})
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "state": state})


@bp.post("/api/sessions")
@login_required
def create_session():
    try:
        request_model = _request_from_payload(request.get_json(silent=True) or {})
        session = PersonalTVService.create_session(request_model)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    payload = PersonalTVService.session_payload(session)
    if not payload or not payload["items"]:
        return jsonify({"ok": False, "error": "No eligible programmes match these choices."}), 422
    return jsonify({"ok": True, "session": PersonalTVService.session_payload(session)}), 201


@bp.get("/api/sessions/<session_id>")
@login_required
def get_session(session_id: str):
    session, error = _session_or_404(session_id)
    if error:
        return error
    return jsonify({"ok": True, "session": PersonalTVService.session_payload(session)})


@bp.post("/api/sessions/<session_id>/<action>")
@login_required
def transition_session(session_id: str, action: str):
    session, error = _session_or_404(session_id)
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    try:
        if action == "replace":
            session = PersonalTVService.replace_current_item(
                session, str(payload.get("reason", "unavailable"))
            )
        elif action == "regenerate":
            session = PersonalTVService.regenerate_remainder(session)
        elif action == "progress":
            session = PersonalTVService.record_progress(
                session,
                playhead_seconds=(
                    int(payload["playhead_seconds"])
                    if payload.get("playhead_seconds") is not None
                    else None
                ),
                completion_ratio=(
                    int(payload["completion_ratio"])
                    if payload.get("completion_ratio") is not None
                    else None
                ),
            )
        else:
            session = PersonalTVService.transition(
                session, action, str(payload.get("skip_reason", ""))
            )
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "session": PersonalTVService.session_payload(session)})


@bp.post("/api/sessions/<session_id>/items/<int:item_id>/<action>")
@login_required
def edit_session_item(session_id: str, item_id: int, action: str):
    session, error = _session_or_404(session_id)
    if error:
        return error
    try:
        if action == "replace":
            session = PersonalTVService.replace_item(session, item_id)
        elif action == "remove":
            session = PersonalTVService.remove_item(session, item_id)
        else:
            raise ValueError("Unsupported programme edit.")
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "session": PersonalTVService.session_payload(session)})


@bp.post("/api/sessions/<session_id>/feedback")
@login_required
def feedback(session_id: str):
    session, error = _session_or_404(session_id)
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    try:
        session = PersonalTVService.submit_feedback(
            session, str(payload.get("kind", "")), str(payload.get("reason", ""))
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify(
        {
            "ok": True,
            "session": PersonalTVService.session_payload(session),
            "profile": PersonalTVService.viewer_profile_payload(),
        }
    )


@bp.route("/api/programs", methods=["GET", "POST"])
@login_required
def prepared_programs():
    if request.method == "GET":
        return jsonify({"ok": True, "programs": PersonalTVService.prepared_programs()})
    payload = request.get_json(silent=True) or {}
    try:
        starts_at = datetime.fromisoformat(str(payload.get("starts_at", "")).replace("Z", "+00:00"))
        request_model = _request_from_payload(payload.get("request", {}))
        program = PersonalTVService.prepare_program(
            str(payload.get("name", "")), starts_at, request_model
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "program": {"id": program.id, "name": program.name}}), 201


@bp.post("/api/programs/generate")
@login_required
def generate_programs():
    return jsonify({"ok": True, "programs": PersonalTVService.generate_daypart_programs()})


@bp.post("/api/programs/<program_id>/start")
@login_required
def start_prepared_program(program_id: str):
    program = db.session.get(PreparedTVProgram, program_id)
    if program is None:
        return jsonify({"ok": False, "error": "Prepared programme not found."}), 404
    try:
        session = PersonalTVService.start_prepared_program(program)
        session = PersonalTVService.transition(session, "play")
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "session": PersonalTVService.session_payload(session)})
