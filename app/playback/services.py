from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.extensions import db
from app.history.services import HistoryService
from app.playback.models import MagnetCandidate, PlaybackSource

MAGNET_HASH_PATTERN = re.compile(r"^(?:[A-Fa-f0-9]{40,64}|[A-Za-z2-7]{32})$")


def source_item(source: PlaybackSource) -> dict:
    return {
        "id": source.id,
        "movie_id": source.movie_id,
        "kind": source.kind,
        "label": source.label,
        "status": source.status,
        "selected": source.selected,
        "metadata": source.metadata_json,
    }


def magnet_item(candidate: MagnetCandidate) -> dict:
    return {
        "id": candidate.id,
        "movie_id": candidate.movie_id,
        "info_hash": candidate.info_hash,
        "display_name": candidate.display_name,
        "size_bytes": candidate.size_bytes,
        "review_state": candidate.review_state,
        "approved": candidate.approved,
    }


class PlaybackService:
    @staticmethod
    def player_sources(movie_id: str) -> list[dict]:
        sources = list(
            db.session.scalars(
                db.select(PlaybackSource)
                .where(
                    PlaybackSource.movie_id == movie_id,
                    PlaybackSource.kind == "magnet",
                    PlaybackSource.status == "available",
                )
                .order_by(PlaybackSource.selected.desc(), PlaybackSource.label.asc())
            )
        )
        unique: list[dict] = []
        seen: set[str] = set()
        for source in sources:
            if source.locator in seen:
                continue
            seen.add(source.locator)
            unique.append(
                {
                    "id": source.id,
                    "label": re.sub(r"\s+magnet$", "", source.label, flags=re.IGNORECASE),
                    "kind": source.kind,
                    "selected": source.selected,
                }
            )
        return unique

    @staticmethod
    def magnet_source(*, movie_id: str, source_id: str) -> PlaybackSource | None:
        return db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.id == source_id,
                PlaybackSource.movie_id == movie_id,
                PlaybackSource.kind == "magnet",
                PlaybackSource.status == "available",
            )
        )

    @staticmethod
    def torrent_fallback(*, movie_id: str, label: str) -> PlaybackSource | None:
        return db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie_id,
                PlaybackSource.kind == "torrent",
                PlaybackSource.label == re.sub(
                    r"magnet$", "torrent", label, flags=re.IGNORECASE
                ),
                PlaybackSource.status == "available",
            )
        )

    @staticmethod
    def vidsrc_source(*, movie: dict, base_url: str) -> dict:
        external_ids = dict(movie.get("external_ids") or {})
        imdb_id = ""
        for key in ("imdb_id", "imdb"):
            candidate = str(external_ids.get(key) or "").strip().lower()
            if re.fullmatch(r"tt\d{5,12}", candidate):
                imdb_id = candidate
                break

        normalized_base = base_url.strip().rstrip("/")
        if imdb_id:
            return {
                "provider": "vidsrc",
                "label": "VidSrc",
                "url": f"{normalized_base}/{imdb_id}",
                "match": "imdb",
            }

        raise ValueError("An IMDb ID is required for VidSrc playback.")

    @staticmethod
    def workspace(movie_id: str) -> dict:
        sources = list(
            db.session.scalars(
                db.select(PlaybackSource)
                .where(PlaybackSource.movie_id == movie_id)
                .order_by(PlaybackSource.selected.desc(), PlaybackSource.created_at.desc())
            )
        )
        magnets = list(
            db.session.scalars(
                db.select(MagnetCandidate)
                .where(MagnetCandidate.movie_id == movie_id)
                .order_by(MagnetCandidate.created_at.desc())
            )
        )
        return {
            "sources": [source_item(source) for source in sources],
            "magnets": [magnet_item(candidate) for candidate in magnets],
        }

    @staticmethod
    def add_local_file(*, movie_id: str, path_value: str, label: str = "") -> PlaybackSource:
        path = Path(path_value).expanduser()
        if not path.is_absolute() or not path.is_file():
            raise ValueError("Playback file must be an existing absolute file path.")
        resolved = path.resolve(strict=True)
        source = PlaybackSource(
            movie_id=movie_id,
            kind="local_file",
            label=(label.strip() or resolved.name)[:300],
            locator=str(resolved),
            metadata_json={"suffix": resolved.suffix.lower()},
        )
        db.session.add(source)
        HistoryService.record(
            domain="movies",
            entity_type="movie",
            entity_id=movie_id,
            event_type="playback_source_added",
            label=f"Added local playback source: {source.label}",
        )
        db.session.commit()
        return source

    @staticmethod
    def add_magnet(*, movie_id: str, magnet_uri: str) -> MagnetCandidate:
        parsed = urlparse(magnet_uri.strip())
        if parsed.scheme.lower() != "magnet":
            raise ValueError("A magnet URI is required.")
        values = parse_qs(parsed.query)
        exact_topic = str((values.get("xt") or [""])[0])
        prefix = "urn:btih:"
        if not exact_topic.lower().startswith(prefix):
            raise ValueError("Magnet URI must contain a BitTorrent info hash.")
        info_hash = exact_topic[len(prefix) :]
        if not MAGNET_HASH_PATTERN.fullmatch(info_hash):
            raise ValueError("Magnet info hash is invalid.")
        candidate = MagnetCandidate(
            movie_id=movie_id,
            info_hash=info_hash.lower(),
            display_name=str((values.get("dn") or [""])[0])[:500],
            magnet_uri=magnet_uri.strip(),
            review_state="review_required",
        )
        db.session.add(candidate)
        HistoryService.record(
            domain="movies",
            entity_type="movie",
            entity_id=movie_id,
            event_type="magnet_candidate_added",
            label="Added a magnet candidate for review",
        )
        db.session.commit()
        return candidate

    @staticmethod
    def approve_magnet(candidate: MagnetCandidate) -> None:
        candidate.approved = True
        candidate.review_state = "approved"
        db.session.commit()
