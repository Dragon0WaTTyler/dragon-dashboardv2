from __future__ import annotations

from typing import Any

from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.movies.models import Movie

SORTS = {
    "title_asc": Movie.normalized_title.asc(),
    "title_desc": Movie.normalized_title.desc(),
    "score_desc": Movie.personal_score.desc().nullslast(),
    "year_desc": Movie.year.desc().nullslast(),
    "recently_updated": Movie.updated_at.desc(),
}


class MovieRepository:
    @staticmethod
    def get(movie_id: str) -> Movie | None:
        return db.session.scalar(
            db.select(Movie).options(selectinload(Movie.progress)).where(Movie.id == movie_id)
        )

    @staticmethod
    def list(filters: dict[str, Any], *, limit: int, offset: int) -> tuple[list[Movie], int]:
        query = db.select(Movie).options(selectinload(Movie.progress))
        count_query = db.select(func.count()).select_from(Movie)
        conditions = []
        search = str(filters.get("q") or "").strip().lower()
        if search:
            pattern = f"%{search}%"
            conditions.append(
                or_(
                    Movie.normalized_title.like(pattern),
                    func.lower(Movie.original_title).like(pattern),
                )
            )
        for key, column in (
            ("status", Movie.status),
            ("category", Movie.category),
            ("source", Movie.source),
        ):
            value = str(filters.get(key) or "").strip()
            if value:
                conditions.append(column == value)
        genre = str(filters.get("genre") or "").strip().lower()
        if genre:
            conditions.append(func.lower(cast(Movie.genres, String)).like(f'%"{genre}"%'))
        if filters.get("year_min") is not None:
            conditions.append(Movie.year >= filters["year_min"])
        if filters.get("year_max") is not None:
            conditions.append(Movie.year <= filters["year_max"])
        if filters.get("score_min") is not None:
            conditions.append(Movie.personal_score >= filters["score_min"])
        if filters.get("score_max") is not None:
            conditions.append(Movie.personal_score <= filters["score_max"])
        if conditions:
            query = query.where(*conditions)
            count_query = count_query.where(*conditions)
        total = int(db.session.scalar(count_query) or 0)
        order = SORTS.get(str(filters.get("sort") or ""), Movie.updated_at.desc())
        items = list(db.session.scalars(query.order_by(order).limit(limit).offset(offset)))
        return items, total

    @staticmethod
    def filter_options() -> dict[str, list[str]]:
        def values(column):
            query = db.select(column).where(column != "").distinct().order_by(column)
            return [str(value) for value in db.session.scalars(query) if value]

        genres: set[str] = set()
        for movie_genres in db.session.scalars(db.select(Movie.genres)):
            for genre in movie_genres or []:
                name = genre.get("name") if isinstance(genre, dict) else genre
                if name:
                    genres.add(str(name))
        return {
            "statuses": values(Movie.status),
            "categories": values(Movie.category),
            "sources": values(Movie.source),
            "genres": sorted(genres, key=str.casefold),
        }
