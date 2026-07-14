from flask import Blueprint, abort, current_app, render_template, request
from flask_login import login_required

from app.ai.services import AIService

bp = Blueprint("ai", __name__, url_prefix="/ai")


@bp.get("/workspace")
@login_required
def workspace():
    try:
        view = AIService.workspace(
            mode=str(request.args.get("mode") or "movie_curation"),
            context_type=str(request.args.get("context_type") or "none"),
            context_id=str(request.args.get("context_id") or ""),
            enabled=bool(current_app.config["DRAGON_AI_ENABLED"]),
        )
    except ValueError:
        abort(404)
    return render_template("ai/workspace.html", active_module="more", workspace=view)
