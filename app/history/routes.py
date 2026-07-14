from flask import Blueprint, render_template, request
from flask_login import login_required

from app.history.services import HistoryService, event_item

bp = Blueprint("history", __name__, url_prefix="/history")


@bp.get("")
@login_required
def index():
    domain = str(request.args.get("domain") or "")
    events = HistoryService.list(domain=domain)
    return render_template(
        "history/index.html",
        active_module="more",
        domain=domain,
        events=[event_item(event) for event in events],
    )
