from __future__ import annotations

from datetime import UTC, timedelta

from sqlalchemy import func, select, update
from werkzeug.datastructures import MultiDict

from app.extensions import db
from app.services.streaming import UnsafeStreamUrl, validate_stream_url
from app.shared.time import utc_now

from .models import Article, ReadingSource
from .services import ReadingService

LANGUAGES = {"auto", "ar", "en", "fr", "de"}
REFRESH_INTERVALS = {15, 30, 60, 180, 360, 720, 1440}
ARTICLE_LIMITS = {25, 50, 100, 200, 500}


class ReadingSourceValidationError(ValueError):
    pass


class ReadingSourceManager:
    @staticmethod
    def list_sources() -> list[dict]:
        counts = {
            str(source_id): int(count)
            for source_id, count in db.session.execute(
                select(Article.source_id, func.count(Article.id))
                .where(Article.source_id.is_not(None))
                .group_by(Article.source_id)
            )
        }
        sources = list(db.session.scalars(select(ReadingSource).order_by(ReadingSource.name)))
        return [{"record": source, "article_count": counts.get(source.id, 0)} for source in sources]

    @staticmethod
    def due_source_ids() -> set[str]:
        now = utc_now()
        due: set[str] = set()
        for source in db.session.scalars(
            select(ReadingSource).where(
                ReadingSource.active.is_(True),
                ReadingSource.auto_refresh.is_(True),
            )
        ):
            last_success = source.last_success_at
            if last_success is not None and last_success.tzinfo is None:
                last_success = last_success.replace(tzinfo=UTC)
            if last_success is None or now - last_success >= timedelta(
                minutes=source.refresh_interval_minutes
            ):
                due.add(source.id)
        return due

    @staticmethod
    def list_categories() -> list[dict]:
        return [
            {
                "name": category or "Uncategorized",
                "value": category,
                "sources": int(sources),
                "active": int(active or 0),
            }
            for category, sources, active in db.session.execute(
                select(
                    ReadingSource.category,
                    func.count(ReadingSource.id),
                    func.sum(ReadingSource.active),
                )
                .group_by(ReadingSource.category)
                .order_by(ReadingSource.category)
            )
        ]

    @staticmethod
    def create(values: MultiDict) -> ReadingSource:
        prepared = ReadingSourceManager._prepared(values)
        if db.session.scalar(
            select(ReadingSource).where(ReadingSource.feed_url == prepared["feed_url"])
        ):
            raise ReadingSourceValidationError("This RSS URL is already connected.")
        source = ReadingSource(**prepared)
        db.session.add(source)
        db.session.commit()
        return source

    @staticmethod
    def test_configuration(values: MultiDict, client) -> int:
        """Validate and test a draft feed without persisting it."""
        prepared = ReadingSourceManager._prepared(values)
        try:
            result = client.fetch(prepared["feed_url"])
        except Exception as exc:
            raise ReadingSourceValidationError(str(exc)) from exc
        return len(list(result.get("entries") or []))

    @staticmethod
    def update(source: ReadingSource, values: MultiDict) -> ReadingSource:
        prepared = ReadingSourceManager._prepared(values)
        duplicate = db.session.scalar(
            select(ReadingSource).where(
                ReadingSource.feed_url == prepared["feed_url"],
                ReadingSource.id != source.id,
            )
        )
        if duplicate:
            raise ReadingSourceValidationError("This RSS URL is already connected.")
        for key, value in prepared.items():
            setattr(source, key, value)
        source.health_state = "unknown"
        source.health_message = "Settings changed; test or refresh this feed."
        db.session.commit()
        return source

    @staticmethod
    def test(source: ReadingSource, client) -> int:
        source.last_tested_at = utc_now()
        try:
            result = client.fetch(source.feed_url)
            entries = list(result.get("entries") or [])
            source.health_state = "healthy"
            source.health_message = f"Connection succeeded with {len(entries)} entries."
            db.session.commit()
            return len(entries)
        except Exception as exc:
            db.session.rollback()
            failed = db.session.get(ReadingSource, source.id)
            if failed:
                failed.health_state = "error"
                failed.health_message = str(exc)[:500]
                failed.last_tested_at = utc_now()
                db.session.commit()
            raise ReadingSourceValidationError(str(exc)) from exc

    @staticmethod
    def refresh(source: ReadingSource, client) -> dict[str, int]:
        if not source.active:
            raise ReadingSourceValidationError("Enable this RSS source before refreshing it.")
        return ReadingService.sync_sources(client, source_ids={source.id})

    @staticmethod
    def toggle(source: ReadingSource) -> bool:
        source.active = not source.active
        db.session.commit()
        return source.active

    @staticmethod
    def delete(source: ReadingSource, *, keep_articles: bool) -> None:
        if keep_articles:
            db.session.execute(
                update(Article).where(Article.source_id == source.id).values(source_id=None)
            )
        else:
            for article in db.session.scalars(
                select(Article).where(Article.source_id == source.id)
            ):
                db.session.delete(article)
        db.session.delete(source)
        db.session.commit()

    @staticmethod
    def update_category(current: str, values: MultiDict) -> None:
        name = str(values.get("name") or "").strip()[:120]
        if not name:
            raise ReadingSourceValidationError("Category name is required.")
        db.session.execute(
            update(ReadingSource)
            .where(ReadingSource.category == current)
            .values(category=name, active=values.get("active") == "on")
        )
        db.session.commit()

    @staticmethod
    def _prepared(values: MultiDict) -> dict:
        name = str(values.get("name") or "").strip()
        feed_url = str(values.get("feed_url") or "").strip()
        category = str(values.get("category") or "").strip()
        language = str(values.get("language") or "auto")
        try:
            interval = int(values.get("refresh_interval_minutes") or 60)
            maximum = int(values.get("maximum_articles") or 200)
        except (TypeError, ValueError) as exc:
            raise ReadingSourceValidationError("Choose valid refresh and article limits.") from exc
        if not name:
            raise ReadingSourceValidationError("Feed name is required.")
        try:
            feed_url = validate_stream_url(feed_url)
        except UnsafeStreamUrl as exc:
            raise ReadingSourceValidationError(str(exc)) from exc
        if language not in LANGUAGES:
            raise ReadingSourceValidationError("Choose a supported feed language.")
        if interval not in REFRESH_INTERVALS:
            raise ReadingSourceValidationError("Choose a supported refresh interval.")
        if maximum not in ARTICLE_LIMITS:
            raise ReadingSourceValidationError("Choose a supported article limit.")
        return {
            "name": name[:240],
            "feed_url": feed_url[:1000],
            "category": category[:120],
            "language": language,
            "active": values.get("active") == "on",
            "auto_refresh": values.get("auto_refresh") == "on",
            "refresh_interval_minutes": interval,
            "maximum_articles": maximum,
            "download_fulltext": values.get("download_fulltext") == "on",
            "download_images": values.get("download_images") == "on",
        }
