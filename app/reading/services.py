from __future__ import annotations

from sqlalchemy import or_

from app.extensions import db
from app.history.services import HistoryService
from app.reading.models import Article, ReadingSource
from app.reading.text import article_paragraphs, normalize_article_text
from app.shared.operations.service import safe_error_text
from app.shared.text import text_direction
from app.shared.time import utc_iso, utc_now

ARTICLE_STATUSES = {"unread", "reading", "finished", "saved"}


def article_item(article: Article) -> dict:
    return {
        "id": article.id,
        "title": article.title,
        "direction": text_direction(article.title),
        "source": article.source.name if article.source else "Unknown source",
        "source_id": article.source_id,
        "author": article.author,
        "topic": article.topic,
        "excerpt": normalize_article_text(article.excerpt),
        "image_url": article.image_url,
        "status": article.status,
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "fulltext_state": article.fulltext_state,
    }


def article_detail(article: Article) -> dict:
    content_text = normalize_article_text(article.content_text)
    return {
        **article_item(article),
        "url": article.url,
        "content_text": content_text,
        "content_paragraphs": article_paragraphs(content_text),
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
            content = normalize_article_text(result.get("content_text"))
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

    @staticmethod
    def sync_sources(client) -> dict[str, int]:
        sources = list(
            db.session.scalars(
                db.select(ReadingSource)
                .where(ReadingSource.active.is_(True))
                .order_by(ReadingSource.name)
            )
        )
        counts = {
            "sources": len(sources),
            "sources_synced": 0,
            "sources_failed": 0,
            "created": 0,
            "updated": 0,
            "changed": 0,
        }
        for source in sources:
            try:
                result = client.fetch(source.feed_url)
                entries = list(result.get("entries") or [])
            except Exception as exc:
                source.health_state = "error"
                source.health_message = safe_error_text(exc)
                counts["sources_failed"] += 1
                continue

            for entry in entries:
                external_id = str(entry.get("external_id") or entry.get("url") or "")[:500]
                article_url = str(entry.get("url") or "")[:1500]
                if not external_id or not article_url:
                    continue
                article = db.session.scalar(
                    db.select(Article).where(
                        Article.source_id == source.id,
                        or_(Article.external_id == external_id, Article.url == article_url),
                    )
                )
                values = {
                    "external_id": external_id,
                    "title": str(entry.get("title") or "Untitled article")[:600],
                    "url": article_url,
                    "author": str(entry.get("author") or "")[:240],
                    "topic": str(entry.get("topic") or "")[:160],
                    "excerpt": str(entry.get("excerpt") or "")[:20_000],
                    "image_url": str(entry.get("image_url") or "")[:1000],
                    "published_at": entry.get("published_at"),
                }
                if article is None:
                    db.session.add(Article(source=source, **values))
                    counts["created"] += 1
                    continue
                changed = False
                for field, value in values.items():
                    if getattr(article, field) != value:
                        setattr(article, field, value)
                        changed = True
                if changed:
                    counts["updated"] += 1

            source.health_state = "healthy"
            source.health_message = f"Synced {len(entries)} feed entries."
            source.last_success_at = utc_now()
            counts["sources_synced"] += 1

        counts["changed"] = counts["created"] + counts["updated"]
        db.session.commit()
        return counts
