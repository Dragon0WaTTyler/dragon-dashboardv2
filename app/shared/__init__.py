"""Shared infrastructure with no domain-specific business rules."""

from app.shared.operations import OperationService
from app.shared.snapshots import SnapshotRead, SnapshotStore

__all__ = ["OperationService", "SnapshotRead", "SnapshotStore"]
