from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.shared.time import utc_now


class WorkspaceIntegration(db.Model):
    """Per-user integration configuration kept inside the synced workspace cache."""

    __tablename__ = "workspace_integrations"

    provider: Mapped[str] = mapped_column(String(80), primary_key=True)
    settings_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
