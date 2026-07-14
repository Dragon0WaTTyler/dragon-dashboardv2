from __future__ import annotations

from app.extensions import db
from app.history.services import HistoryService
from app.reading.models import Article
from app.shared.operations.service import safe_error_text
from app.shared.time import utc_iso

ARTICLE_STATUSES = {"unread", "reading", "finished", "saved"}


def article_item(article: Article) -> dict:
    return {
        "id": article.id,
        "title": article.title,
        "source": article.source.name if article.source else "Unknown source",
        "source_id": article.source_id,
        "author": article.author,
        "topic": article.topic,
        "excerpt": article.excerpt,
        "image_url": article.image_url,
        "status": article.status,
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "fulltext_state": article.fulltext_state,
    }


def article_detail(article: Article) -> dict:
    return {
        **article_item(article),
        "url": article.url,
        "content_text": article.content_text,
        "fulltext_error": article.fulltext_error,
        "history": article.history,
    }


class ReadingService:
    @staticmethod
    def continue_reading(limit: int = 4) -> list[dict]:
        from app.reading.repositories import ReadingRepository

        articles = ReadingRepository.list(status="reading", limit=limit)
        return [article_item(article) for article in articles]

    @staticmethod
    def article_of_day() -> dict | None:
        from app.reading.repositories import ReadingRepository

        articles = ReadingRepository.list(status="unread", limit=1)
        return article_item(articles[0]) if articles else None

    @staticmethod
    def extract_fulltext(article: Article, extractor) -> None:
        try:
            result = extractor.extract(article.url)
            content = str(result.get("content_text") or "").replace("\x00", "").strip()
            if not content:
                raise ValueError("Extractor returned no readable text.")
        except Exception as exc:
            article.fulltext_state = "failed"
            article.fulltext_error = safe_error_text(exc)
            db.session.commit()
            raise ValueError("Full-text extraction failed safely.") from exc
        article.content_text = content[:1_000_000]
        article.fulltext_state = "cached"
        article.fulltext_error = ""
        if article.status == "unread":
            article.status = "reading"
        article.history = [*article.history, {"event": "fulltext_cached", "at": utc_iso()}]
        HistoryService.record(
            domain="reading",
            entity_type="article",
            entity_id=article.id,
            event_type="fulltext_cached",
            label=f"Cached full text for {article.title}",
        )
        db.session.commit()

    @staticmethod
    def set_status(article: Article, status: str) -> None:
        if status not in ARTICLE_STATUSES:
            raise ValueError("Unknown reading status.")
        article.status = status
        article.history = [*article.history, {"event": status, "at": utc_iso()}]
        HistoryService.record(
            domain="reading",
            entity_type="article",
            entity_id=article.id,
            event_type="status",
            label=f"{article.title}: {status}",
        )
        db.session.commit()

    @staticmethod
    def extraction_status(article: Article) -> dict:
        return {
            "article_id": article.id,
            "state": article.fulltext_state,
            "error": article.fulltext_error or None,
            "cached": bool(article.content_text),
        }
