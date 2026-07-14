from __future__ import annotations

from app.extensions import db
from app.german.models import GermanResource, VocabularyItem
from app.history.services import HistoryService
from app.shared.time import utc_now


def resource_item(resource: GermanResource) -> dict:
    return {
        "id": resource.id,
        "title": resource.title,
        "kind": resource.kind,
        "url": resource.url,
        "source": resource.source,
        "level": resource.level,
        "description": resource.description,
        "completed": resource.completed,
        "progress_percent": resource.progress_percent,
    }


def vocabulary_item(item: VocabularyItem) -> dict:
    return {
        "id": item.id,
        "term": item.term,
        "meaning": item.meaning,
        "example": item.example,
        "level": item.level,
        "tags": item.tags,
        "review_count": item.review_count,
    }


class GermanService:
    @staticmethod
    def workspace(*, kind: str = "") -> dict:
        query = db.select(GermanResource)
        if kind:
            query = query.where(GermanResource.kind == kind)
        resources = list(db.session.scalars(query.order_by(GermanResource.updated_at.desc())))
        vocabulary = list(
            db.session.scalars(
                db.select(VocabularyItem).order_by(VocabularyItem.last_reviewed_at).limit(30)
            )
        )
        return {
            "resources": [resource_item(resource) for resource in resources],
            "vocabulary": [vocabulary_item(item) for item in vocabulary],
        }

    @staticmethod
    def save_progress(resource: GermanResource, progress_percent: int) -> None:
        if not 0 <= progress_percent <= 100:
            raise ValueError("Progress must be between 0 and 100.")
        resource.progress_percent = progress_percent
        resource.completed = progress_percent == 100
        HistoryService.record(
            domain="german",
            entity_type="resource",
            entity_id=resource.id,
            event_type="progress",
            label=f"{resource.title}: {progress_percent}%",
        )
        db.session.commit()

    @staticmethod
    def review_word(item: VocabularyItem) -> None:
        item.review_count += 1
        item.last_reviewed_at = utc_now()
        HistoryService.record(
            domain="german",
            entity_type="vocabulary",
            entity_id=item.id,
            event_type="review",
            label=f"Reviewed {item.term}",
        )
        db.session.commit()
