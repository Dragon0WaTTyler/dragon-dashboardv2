from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from uuid import uuid4

from app.extensions import db
from app.shared.models import Operation
from app.shared.time import utc_now

PATH_PATTERN = re.compile(r"(?:[A-Za-z]:\\|/home/|/Users/)[^\s]+")
SECRET_PATTERN = re.compile(
    r"(?i)(token|secret|password|authorization|api[_-]?key)\s*[:=]\s*[^\s,;]+"
)


def safe_error_text(value: object, *, maximum: int = 280) -> str:
    text = " ".join(str(value or "").split())
    text = PATH_PATTERN.sub("[local path]", text)
    text = SECRET_PATTERN.sub(r"\1=[redacted]", text)
    return text[:maximum]


class OperationService:
    @staticmethod
    def start(*, kind: str, domain: str, scope: str = "all") -> Operation:
        operation = Operation(
            id=str(uuid4()),
            kind=kind,
            domain=domain,
            scope=scope,
            status="running",
            started_at=utc_now(),
        )
        db.session.add(operation)
        db.session.commit()
        return operation

    @staticmethod
    def complete(
        operation: Operation,
        *,
        counts: Mapping[str, int] | None = None,
        warnings: Sequence[str] | None = None,
    ) -> Operation:
        safe_warnings = [safe_error_text(item) for item in (warnings or [])]
        operation.counts = {str(key): int(value) for key, value in (counts or {}).items()}
        operation.warnings = safe_warnings
        operation.status = "completed_with_warnings" if safe_warnings else "completed"
        operation.completed_at = utc_now()
        db.session.commit()
        return operation

    @staticmethod
    def fail(operation: Operation, error: object) -> Operation:
        operation.status = "failed"
        operation.safe_error = safe_error_text(error)
        operation.completed_at = utc_now()
        db.session.commit()
        return operation

    @staticmethod
    def get(operation_id: str) -> Operation | None:
        return db.session.get(Operation, operation_id)

    @staticmethod
    def list_recent(*, domain: str | None = None, limit: int = 25) -> list[Operation]:
        query = db.select(Operation)
        if domain:
            query = query.where(Operation.domain == domain)
        query = query.order_by(Operation.created_at.desc()).limit(max(1, min(limit, 100)))
        return list(db.session.scalars(query))
