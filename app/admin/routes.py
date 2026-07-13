from flask import Blueprint, render_template
from flask_login import login_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.get("/design-system")
@login_required
def design_system():
    return render_template("admin/design_system.html", active_module="more")
