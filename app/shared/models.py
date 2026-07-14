from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.shared.time import utc_now


class Operation(db.Model):
    __tablename__ = "operations"
    __table_args__ = (Index("ix_operations_domain_created", "domain", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    domain: Mapped[str] = mapped_column(String(40), nullable=False)
    scope: Mapped[str] = mapped_column(String(120), default="all", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False)
    counts: Mapped[dict[str, int]] = mapped_column(JSON, default=dict, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    safe_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "domain": self.domain,
            "scope": self.scope,
            "status": self.status,
            "counts": dict(self.counts or {}),
            "warnings": list(self.warnings or []),
            "safe_error": self.safe_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class SnapshotRecord(db.Model):
    __tablename__ = "snapshot_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(255), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), default="fresh", nullable=False)
    message: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_success_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class LegacyIdMap(db.Model):
    __tablename__ = "legacy_id_map"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "entity_type",
            "source_id",
            name="uq_legacy_id_source_entity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_system: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class MigrationRun(db.Model):
    __tablename__ = "migration_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    source_root: Mapped[str] = mapped_column(String(1024), nullable=False)
    manifest_path: Mapped[str | None] = mapped_column(String(1024))
    report_path: Mapped[str | None] = mapped_column(String(1024))
    counts: Mapped[dict[str, int]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
