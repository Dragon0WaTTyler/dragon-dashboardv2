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
        limit: int = 50,
    ):
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
            conditions.append(Article.published_at >= published_since)
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
            .limit(limit)
        )
        return list(db.session.scalars(query))

    @staticmethod
    def sources() -> list[ReadingSource]:
        return list(db.session.scalars(db.select(ReadingSource).order_by(ReadingSource.name)))
