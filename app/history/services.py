from __future__ import annotations

from app.extensions import db
from app.history.models import HistoryEvent


class HistoryService:
    @staticmethod
    def record(
        *,
        domain: str,
        entity_type: str,
        entity_id: str,
        event_type: str,
        label: str,
        metadata: dict | None = None,
        commit: bool = False,
    ) -> HistoryEvent:
        event = HistoryEvent(
            domain=domain,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            label=label[:500],
            metadata_json=metadata or {},
        )
        db.session.add(event)
        if commit:
            db.session.commit()
        return event

    @staticmethod
    def list(*, domain: str = "", limit: int = 100) -> list[HistoryEvent]:
        query = db.select(HistoryEvent)
        if domain:
            query = query.where(HistoryEvent.domain == domain)
        return list(
            db.session.scalars(query.order_by(HistoryEvent.created_at.desc()).limit(limit))
        )


def event_item(event: HistoryEvent) -> dict:
    return {
        "id": event.id,
        "domain": event.domain,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "event_type": event.event_type,
        "label": event.label,
        "metadata": event.metadata_json,
        "created_at": event.created_at.isoformat(),
    }
