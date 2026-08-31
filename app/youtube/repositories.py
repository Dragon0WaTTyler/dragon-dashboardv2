from __future__ import annotations

import hashlib
import re

from sqlalchemy import func, or_

from app.extensions import db
from app.youtube.grouping import ordered_groups
from app.youtube.models import YouTubeVideo


class YouTubeRepository:
    @staticmethod
    def get(video_id: str) -> YouTubeVideo | None:
        return db.session.get(YouTubeVideo, video_id)

    @staticmethod
    def get_by_source_external_id(source: str, external_id: str) -> YouTubeVideo | None:
        return db.session.scalar(
            db.select(YouTubeVideo).where(
                YouTubeVideo.source == source,
                YouTubeVideo.external_id == external_id,
            )
        )

    @staticmethod
    def list(
        *,
        source: str,
        group: str = "",
        q: str = "",
        limit: int | None = 50,
        offset: int = 0,
    ) -> tuple[list[YouTubeVideo], int]:
        conditions = [
            YouTubeVideo.source == source,
            YouTubeVideo.removed_from_source.is_(False),
        ]
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
        query = base.order_by(YouTubeVideo.position, YouTubeVideo.published_at.desc())
        if limit is not None:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)
        items = list(db.session.scalars(query))
        return items, total

    @staticmethod
    def deterministic_window(
        *,
        source: str,
        group: str = "",
        q: str = "",
        seed: str,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[YouTubeVideo], int]:
        """Return a deterministic slice without materialising the whole feed.

        The normal shuffle endpoint intentionally preserves its full-list ordering
        contract.  Home-page rotation only needs a handful of adjacent items, so
        use a deterministic database offset and wrap once at the end instead of
        loading and hashing tens of thousands of videos on every request.
        """

        if limit <= 0:
            return [], 0
        _, total = YouTubeRepository.list(
            source=source,
            group=group,
            q=q,
            limit=1,
        )
        if total <= 0:
            return [], 0
        seed_digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        start = (int(seed_digest, 16) + max(0, offset)) % total
        items, _ = YouTubeRepository.list(
            source=source,
            group=group,
            q=q,
            limit=limit,
            offset=start,
        )
        if len(items) < limit and start:
            wrapped, _ = YouTubeRepository.list(
                source=source,
                group=group,
                q=q,
                limit=limit - len(items),
                offset=0,
            )
            items.extend(wrapped)
        return items, total

    @staticmethod
    def resolve_group(value: str) -> str:
        requested = value.strip()
        if not requested:
            return ""
        groups = YouTubeRepository.groups()
        by_exact = {item["name"]: item["name"] for item in groups}
        if requested in by_exact:
            return by_exact[requested]
        requested_key = _group_key(requested)
        for item in groups:
            if _group_key(item["name"]) == requested_key:
                return item["name"]
        return ""

    @staticmethod
    def ordered_ids(*, source: str, group: str = "") -> list[str]:
        conditions = [
            YouTubeVideo.source == source,
            YouTubeVideo.removed_from_source.is_(False),
        ]
        if group:
            conditions.append(YouTubeVideo.group_name == group)
        return list(
            db.session.scalars(
                db.select(YouTubeVideo.id)
                .where(*conditions)
                .order_by(YouTubeVideo.position, YouTubeVideo.published_at.desc())
            )
        )

    @staticmethod
    def groups() -> list[dict]:
        rows = db.session.execute(
            db.select(YouTubeVideo.group_name, func.count())
            .where(
                YouTubeVideo.source == "pockettube",
                YouTubeVideo.group_name != "",
                YouTubeVideo.removed_from_source.is_(False),
            )
            .group_by(YouTubeVideo.group_name)
            .order_by(YouTubeVideo.group_name)
        )
        return ordered_groups([{"name": name, "count": count} for name, count in rows])


def _group_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", value.casefold())
    return normalized.replace("favorite", "favoret")
