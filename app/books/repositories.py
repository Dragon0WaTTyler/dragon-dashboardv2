from __future__ import annotations

from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from app.books.models import Book
from app.extensions import db


class BookRepository:
    @staticmethod
    def get(book_id: str) -> Book | None:
        return db.session.scalar(
            db.select(Book).options(selectinload(Book.quotes)).where(Book.id == book_id)
        )

    @staticmethod
    def list(*, q: str = "", status: str = "") -> list[Book]:
        conditions = []
        if q.strip():
            pattern = f"%{q.strip().lower()}%"
            conditions.append(
                or_(Book.normalized_title.like(pattern), func.lower(Book.description).like(pattern))
            )
        if status:
            conditions.append(Book.status == status)
        return list(
            db.session.scalars(
                db.select(Book)
                .options(selectinload(Book.quotes))
                .where(*conditions)
                .order_by(Book.updated_at.desc())
            )
        )
