from __future__ import annotations

from flask import Blueprint
from sqlalchemy import text

from app.api.v1.responses import item_response
from app.extensions import db

bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")


@bp.get("/health")
def health():
    db.session.execute(text("SELECT 1"))
    return item_response({"status": "ok", "database": "available"})
