from __future__ import annotations

from sqlalchemy import func, or_

from app.extensions import db
from app.youtube.models import YouTubeVideo


class YouTubeRepository:
    @staticmethod
    def get(video_id: str) -> YouTubeVideo | None:
        return db.session.get(YouTubeVideo, video_id)

    @staticmethod
    def list(
        *, source: str, group: str = "", q: str = "", limit: int = 50, offset: int = 0
    ) -> tuple[list[YouTubeVideo], int]:
        conditions = [YouTubeVideo.source == source]
        if source == "watch_later":
            conditions.append(YouTubeVideo.removed_from_source.is_(False))
        if group:
            conditions.append(YouTubeVideo.group_name == group)
        if q.strip():
            pattern = f"%{q.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(YouTubeVideo.title).like(pattern),
                    func.lower(YouTubeVideo.channel_title).like(pattern),
                )
            )
        base = db.select(YouTubeVideo).where(*conditions)
        total = int(
            db.session.scalar(
                db.select(func.count()).select_from(YouTubeVideo).where(*conditions)
            )
            or 0
        )
        items = list(
            db.session.scalars(
                base.order_by(YouTubeVideo.position, YouTubeVideo.published_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        return items, total

    @staticmethod
    def groups() -> list[dict]:
        rows = db.session.execute(
            db.select(YouTubeVideo.group_name, func.count())
            .where(YouTubeVideo.source == "pockettube", YouTubeVideo.group_name != "")
            .group_by(YouTubeVideo.group_name)
            .order_by(YouTubeVideo.group_name)
        )
        return [{"name": name, "count": count} for name, count in rows]
