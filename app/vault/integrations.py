from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from flask import g, has_request_context

from app.extensions import db
from app.vault.models import WorkspaceIntegration

_PROVIDER = re.compile(r"^[a-z][a-z0-9_-]{0,79}$")


def integration_settings(provider: str) -> dict[str, Any]:
    """Return workspace-owned settings, or an empty mapping outside a workspace."""

    if not _PROVIDER.fullmatch(provider) or not has_request_context():
        return {}
    if getattr(g, "dragon_workspace_engine", None) is None:
        return {}
    record = db.session.get(WorkspaceIntegration, provider)
    return dict(record.settings_json or {}) if record is not None else {}


def update_integration_settings(provider: str, settings: Mapping[str, Any]) -> WorkspaceIntegration:
    """Replace one provider's portable settings after basic provider validation."""

    if not _PROVIDER.fullmatch(provider):
        raise ValueError("Integration provider identifier is invalid.")
    if not has_request_context() or getattr(g, "dragon_workspace_engine", None) is None:
        raise RuntimeError("A personal workspace is required to save integration settings.")
    record = db.session.get(WorkspaceIntegration, provider)
    if record is None:
        record = WorkspaceIntegration(provider=provider)
        db.session.add(record)
    record.settings_json = dict(settings)
    db.session.commit()
    return record
