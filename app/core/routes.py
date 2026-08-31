from __future__ import annotations

from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import text

from app.extensions import db
from app.today.services import TodayService

bp = Blueprint("core", __name__)


@bp.get("/healthz")
def healthz():
    db.session.execute(text("SELECT 1"))
    return {"status": "ok"}


@bp.get("/privacy")
def privacy():
    """Public privacy notice required by OAuth providers."""
    return render_template("legal.html", page="privacy")


@bp.get("/terms")
def terms():
    """Public terms of use required by OAuth providers."""
    return render_template("legal.html", page="terms")


@bp.get("/")
@login_required
def index():
    return render_template(
        "today.html", active_module="today", workspace=TodayService.workspace()
    )
