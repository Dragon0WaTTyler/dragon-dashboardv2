from __future__ import annotations

from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import text

from app.extensions import db

bp = Blueprint("core", __name__)


@bp.get("/healthz")
def healthz():
    db.session.execute(text("SELECT 1"))
    return {"status": "ok"}


@bp.get("/")
@login_required
def index():
    return render_template("today.html", active_module="today")
