from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from flask import g, has_request_context

from app.extensions import db
from app.vault.models import WorkspaceIntegration

_PROVIDER = re.compile(r"^[a-z][a-z0-9_-]{0,79}$")


def personal_workspace_active() -> bool:
    return has_request_context() and getattr(g, "dragon_workspace_engine", None) is not None


def integration_settings(provider: str) -> dict[str, Any]:
    """Return workspace-owned settings, or an empty mapping outside a workspace."""

    if not _PROVIDER.fullmatch(provider) or not personal_workspace_active():
        return {}
    record = db.session.get(WorkspaceIntegration, provider)
    return dict(record.settings_json or {}) if record is not None else {}


def update_integration_settings(provider: str, settings: Mapping[str, Any]) -> WorkspaceIntegration:
    """Replace one provider's portable settings after basic provider validation."""

    if not _PROVIDER.fullmatch(provider):
        raise ValueError("Integration provider identifier is invalid.")
    if not personal_workspace_active():
        raise RuntimeError("A personal workspace is required to save integration settings.")
    record = db.session.get(WorkspaceIntegration, provider)
    if record is None:
        record = WorkspaceIntegration(provider=provider)
        db.session.add(record)
    record.settings_json = dict(settings)
    db.session.commit()
    return record
