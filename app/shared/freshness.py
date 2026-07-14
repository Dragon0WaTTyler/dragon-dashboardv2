from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.extensions import db
from app.shared.models import SnapshotRecord

DEFAULT_DOMAINS = (
    "movies",
    "youtube_watch_later",
    "youtube_pockettube",
    "reading",
    "books",
    "chess",
)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def serialize_freshness(record: SnapshotRecord | None, domain: str) -> dict[str, Any]:
    if record is None:
        return {
            "domain": domain,
            "state": "missing",
            "snapshot_version": None,
            "generated_at": None,
            "last_success_at": None,
            "age_seconds": None,
            "is_stale": False,
            "source": "local_snapshot",
            "message": "No local snapshot is available yet.",
            "active_operation_id": None,
        }
    generated_at = _as_utc(record.generated_at)
    last_success_at = _as_utc(record.last_success_at)
    age_seconds = None
    if last_success_at:
        age_seconds = max(0, int((datetime.now(UTC) - last_success_at).total_seconds()))
    return {
        "domain": record.domain,
        "state": record.state,
        "snapshot_version": record.schema_version,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z") if generated_at else None,
        "last_success_at": (
            last_success_at.isoformat().replace("+00:00", "Z") if last_success_at else None
        ),
        "age_seconds": age_seconds,
        "is_stale": record.state == "stale",
        "source": "local_snapshot",
        "message": record.message,
        "active_operation_id": None,
    }


def list_freshness() -> list[dict[str, Any]]:
    records = {record.domain: record for record in db.session.scalars(db.select(SnapshotRecord))}
    ordered = list(DEFAULT_DOMAINS)
    ordered.extend(sorted(domain for domain in records if domain not in DEFAULT_DOMAINS))
    return [serialize_freshness(records.get(domain), domain) for domain in ordered]


def get_freshness(domain: str) -> dict[str, Any]:
    record = db.session.scalar(db.select(SnapshotRecord).where(SnapshotRecord.domain == domain))
    return serialize_freshness(record, domain)
