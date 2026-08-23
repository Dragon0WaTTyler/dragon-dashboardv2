from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.reading.models import Article, ReadingSource


class ReadingRepository:
    @staticmethod
    def get(article_id: str) -> Article | None:
        return db.session.scalar(
            db.select(Article).options(joinedload(Article.source)).where(Article.id == article_id)
        )

    @staticmethod
    def list(
        *,
        q: str = "",
        source_id: str = "",
        status: str = "",
        sort: str = "recent",
        published_since: datetime | None = None,
        published_before: datetime | None = None,
        saved_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ):
        conditions = ReadingRepository._conditions(
            q=q,
            source_id=source_id,
            status=status,
            published_since=published_since,
            published_before=published_before,
            saved_only=saved_only,
        )
        order = (
            (func.lower(Article.title).asc(), Article.published_at.desc())
            if sort == "title"
            else (Article.published_at.desc(), Article.created_at.desc())
        )
        query = (
            db.select(Article)
            .options(joinedload(Article.source))
            .where(*conditions)
            .order_by(*order)
            .offset(max(offset, 0))
            .limit(limit)
        )
        return list(db.session.scalars(query))

    @staticmethod
    def count(
        *,
        q: str = "",
        source_id: str = "",
        status: str = "",
        published_since: datetime | None = None,
        published_before: datetime | None = None,
        saved_only: bool = False,
    ) -> int:
        conditions = ReadingRepository._conditions(
            q=q,
            source_id=source_id,
            status=status,
            published_since=published_since,
            published_before=published_before,
            saved_only=saved_only,
        )
        return int(db.session.scalar(db.select(func.count(Article.id)).where(*conditions)) or 0)

    @staticmethod
    def _conditions(
        *,
        q: str,
        source_id: str,
        status: str,
        published_since: datetime | None,
        published_before: datetime | None,
        saved_only: bool,
    ) -> list:
        conditions = []
        if q.strip():
            pattern = f"%{q.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(Article.title).like(pattern),
                    func.lower(Article.excerpt).like(pattern),
                )
            )
        if source_id:
            conditions.append(Article.source_id == source_id)
        if status:
            conditions.append(Article.status == status)
        if published_since:
            # Imported feeds do not always expose a publication date. Keep those
            # articles visible in Today's inbox instead of making them disappear
            # until the source starts supplying one.
            conditions.append(
                or_(Article.published_at >= published_since, Article.published_at.is_(None))
            )
        if published_before:
            conditions.append(Article.published_at < published_before)
        if saved_only:
            conditions.append(Article.is_saved.is_(True))
        return conditions

    @staticmethod
    def sources() -> list[ReadingSource]:
        return list(db.session.scalars(db.select(ReadingSource).order_by(ReadingSource.name)))
