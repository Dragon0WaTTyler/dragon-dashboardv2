from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from urllib.parse import parse_qs, urlparse

from app.extensions import db
from app.history.services import HistoryService
from app.playback.identity import PlaybackIdentity
from app.playback.models import (
    MagnetCandidate,
    PlaybackProviderPreference,
    PlaybackSource,
    ProviderAvailability,
)
from app.playback.providers import (
    INDEXED_EMBED_PROVIDER_SPECS,
    PlaybackProvider,
    ProviderProbeResult,
    ResolvedPlayback,
    VidSrcProvider,
    indexed_embed_provider_spec,
)
from app.shared.time import utc_now

MAGNET_HASH_PATTERN = re.compile(r"^(?:[A-Fa-f0-9]{40,64}|[A-Za-z2-7]{32})$")
PROVIDER_AVAILABILITY_STATUSES = {"UNKNOWN", "AVAILABLE", "UNAVAILABLE", "DEGRADED"}
PROVIDER_PROBE_LEVELS = {"", "REACHABLE", "EMBED_READY", "PLAYBACK_CONFIRMED"}
AUTHORIZED_EMBED_AUTHORIZATION_STATUSES = frozenset(
    {"catalog_authorized", "manual_authorized"}
)
DEFAULT_PROVIDER_PRIORITIES = {
    **{spec.key: spec.default_priority for spec in INDEXED_EMBED_PROVIDER_SPECS},
    "vidsrc": 100,
}


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _optional_int(value) -> int | None:
    try:
        return int(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None


def _tv_source_scope(source: PlaybackSource) -> tuple[int | None, int | None, str, dict, bool]:
    metadata = dict(source.metadata_json or {})
    season = _optional_int(source.season)
    if season is None:
        season = _optional_int(metadata.get("season"))
    episode = _optional_int(source.episode)
    if episode is None:
        episode = _optional_int(metadata.get("episode"))
    source_role = str(source.source_role or metadata.get("source_role") or "")
    season_pack = bool(
        metadata.get("season_pack")
        or source_role == "season_pack_fallback"
        or str(metadata.get("release_mode") or "") == "season_pack"
    )
    if not source_role:
        if season_pack:
            source_role = "season_pack_fallback"
        elif episode is not None:
            source_role = "exact_episode"
    return season, episode, source_role, metadata, season_pack


def _tv_source_matches_episode(source: PlaybackSource, *, season: int, episode: int) -> bool:
    source_season, source_episode, _source_role, _metadata, season_pack = _tv_source_scope(source)
    if source_season != season:
        return False
    if season_pack:
        return True
    return source_episode == episode


def _tv_episode_sources(movie_id: str, *, season: int, episode: int) -> list[PlaybackSource]:
    rows = list(
        db.session.scalars(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie_id,
                PlaybackSource.kind == "magnet",
                PlaybackSource.status == "available",
            )
        )
    )
    return [row for row in rows if _tv_source_matches_episode(row, season=season, episode=episode)]


def source_item(source: PlaybackSource) -> dict:
    return {
        "id": source.id,
        "movie_id": source.movie_id,
        "kind": source.kind,
        "label": source.label,
        "status": source.status,
        "selected": source.selected,
        "season": source.season,
        "episode": source.episode,
        "source_role": source.source_role,
        "metadata": source.metadata_json,
    }


def _player_source_metadata(metadata: dict) -> dict:
    return {
        "quality": str(metadata.get("quality_label") or metadata.get("quality") or ""),
        "codec": str(metadata.get("codec_label") or metadata.get("codec") or ""),
        "playback": str(metadata.get("playback_label") or metadata.get("playback") or ""),
        "size": str(metadata.get("size_label") or metadata.get("size") or ""),
        "hdr": bool(metadata.get("hdr") or metadata.get("is_hdr")),
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
    def last_selected_source(
        movie_id: str, *, season: int | None = None, episode: int | None = None
    ) -> PlaybackSource | None:
        scope_key = PlaybackIdentity(movie_id=movie_id, season=season, episode=episode).scope_key
        return db.session.scalar(
            db.select(PlaybackSource)
            .where(
                PlaybackSource.movie_id == movie_id,
                PlaybackSource.scope_key == scope_key,
                PlaybackSource.selected.is_(True),
            )
            .order_by(PlaybackSource.updated_at.desc())
        )

    @staticmethod
    def mark_source_selected(source: PlaybackSource) -> None:
        db.session.execute(
            db.update(PlaybackSource)
            .where(
                PlaybackSource.movie_id == source.movie_id,
                PlaybackSource.scope_key == source.scope_key,
            )
            .values(selected=False)
        )
        source.selected = True
        db.session.commit()

    @staticmethod
    def provider_preferences(provider_keys: set[str] | frozenset[str]) -> dict[str, dict]:
        keys = {str(key).strip() for key in provider_keys if str(key).strip()}
        if not keys:
            return {}
        rows = {
            row.provider: row
            for row in db.session.scalars(
                db.select(PlaybackProviderPreference).where(
                    PlaybackProviderPreference.provider.in_(keys)
                )
            )
        }
        return {
            key: {
                "provider": key,
                "enabled": rows.get(key).enabled if key in rows else True,
                "priority": (
                    rows.get(key).priority
                    if key in rows
                    else DEFAULT_PROVIDER_PRIORITIES.get(key, 100)
                ),
                "background_checks": rows.get(key).background_checks if key in rows else False,
            }
            for key in keys
        }

    @staticmethod
    def enabled_provider_keys(provider_keys: set[str] | frozenset[str]) -> frozenset[str]:
        return frozenset(
            key
            for key, preference in PlaybackService.provider_preferences(provider_keys).items()
            if preference["enabled"]
        )

    @staticmethod
    def save_provider_preference(
        *, provider: str, enabled: bool, priority: int, background_checks: bool
    ) -> PlaybackProviderPreference:
        provider = provider.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", provider):
            raise ValueError("Playback provider is invalid.")
        preference = db.session.get(PlaybackProviderPreference, provider)
        if preference is None:
            preference = PlaybackProviderPreference(provider=provider)
            db.session.add(preference)
        preference.enabled = bool(enabled)
        preference.priority = max(0, min(int(priority), 10_000))
        preference.background_checks = bool(background_checks)
        db.session.commit()
        return preference

    @staticmethod
    def indexed_embed_sources(
        movie_id: str,
        *,
        season: int | None = None,
        episode: int | None = None,
        enabled_providers: set[str] | frozenset[str] | None = None,
        provider_priorities: dict[str, int] | None = None,
    ) -> list[dict]:
        if (season is None) != (episode is None):
            raise ValueError("TV playback requires both a season and an episode.")
        scope_key = PlaybackIdentity(
            movie_id=movie_id,
            season=season,
            episode=episode,
        ).scope_key
        filters = [
            PlaybackSource.movie_id == movie_id,
            PlaybackSource.kind == "embed",
            PlaybackSource.source_type == "known_embed",
            PlaybackSource.scope_key == scope_key,
            PlaybackSource.enabled.is_(True),
            PlaybackSource.authorization_status.in_(AUTHORIZED_EMBED_AUTHORIZATION_STATUSES),
        ]
        if enabled_providers is not None:
            filters.append(PlaybackSource.provider.in_(enabled_providers))
        rows = list(
            db.session.scalars(
                db.select(PlaybackSource)
                .where(*filters)
                .order_by(
                    PlaybackSource.priority_override.asc().nulls_last(), PlaybackSource.label.asc()
                )
            )
        )
        availability_by_source_id = (
            {
                availability.playback_source_id: availability
                for availability in db.session.scalars(
                    db.select(ProviderAvailability).where(
                        ProviderAvailability.playback_source_id.in_([row.id for row in rows])
                    )
                )
            }
            if rows
            else {}
        )
        items = [
            (
                {
                    "id": row.id,
                    "provider": row.provider,
                    "label": row.label,
                    "language": row.language,
                    "subtitle_languages": list(row.subtitle_languages or []),
                    "quality": row.quality,
                    "playback_mode": "embed",
                    "selected": row.selected,
                },
                row.priority_override,
            )
            for row in rows
            # A fresh negative result is useful operational memory.  Unknown and
            # stale records intentionally remain visible: neither proves that a
            # source is unavailable, and rendering this list must stay local-only.
            if not (
                (availability := availability_by_source_id.get(row.id))
                and availability.status == "UNAVAILABLE"
                and ProviderAvailabilityService.is_fresh(availability)
            )
        ]
        priorities = provider_priorities or {}
        return [
            item
            for item, _ in sorted(
                items,
                key=lambda pair: (
                    pair[1] if pair[1] is not None else priorities.get(pair[0]["provider"], 100),
                    priorities.get(pair[0]["provider"], 100),
                    pair[0]["label"].casefold(),
                ),
            )
        ]

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
        seen_locators: set[str] = set()
        seen_labels: set[str] = set()
        for source in sources:
            label = re.sub(r"\s+magnet$", "", source.label, flags=re.IGNORECASE).strip()
            label_key = label.casefold()
            if source.locator in seen_locators or label_key in seen_labels:
                continue
            seen_locators.add(source.locator)
            seen_labels.add(label_key)
            metadata = dict(source.metadata_json or {})
            unique.append(
                {
                    "id": source.id,
                    "label": label,
                    "kind": source.kind,
                    "selected": source.selected,
                    "season_pack": bool(metadata.get("season_pack")),
                    "season": metadata.get("season"),
                    "episode": metadata.get("episode"),
                    "release_mode": str(metadata.get("release_mode") or ""),
                    "player_metadata": _player_source_metadata(metadata),
                }
            )
        return unique

    @staticmethod
    def tv_episode_player_sources(movie_id: str, *, season: int, episode: int) -> list[dict]:
        rows = _tv_episode_sources(movie_id, season=season, episode=episode)
        sources = sorted(
            rows,
            key=lambda source: (
                0 if _tv_source_scope(source)[2] == "exact_episode" else 1,
                0 if source.selected else 1,
                str(source.label or "").casefold(),
            ),
        )
        unique: list[dict] = []
        seen_locators: set[str] = set()
        for source in sources:
            if source.locator in seen_locators:
                continue
            seen_locators.add(source.locator)
            source_season, source_episode, source_role, metadata, season_pack = _tv_source_scope(
                source
            )
            label = re.sub(r"\s+magnet$", "", source.label, flags=re.IGNORECASE).strip()
            if season_pack and "season pack" not in label.casefold():
                label = f"{label} season pack"
            unique.append(
                {
                    "id": source.id,
                    "label": label,
                    "kind": source.kind,
                    "selected": source.selected,
                    "season_pack": season_pack,
                    "season": source_season,
                    "episode": source_episode,
                    "release_mode": str(metadata.get("release_mode") or ""),
                    "source_role": source_role,
                    "player_metadata": _player_source_metadata(metadata),
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
                PlaybackSource.label == re.sub(r"magnet$", "torrent", label, flags=re.IGNORECASE),
                PlaybackSource.status == "available",
            )
        )

    @staticmethod
    def vidsrc_source(*, movie: dict, base_url: str) -> dict:
        identity = PlaybackIdentity.from_context(movie)
        return VidSrcProvider(base_url=base_url).resolve(identity).response_item()

    @staticmethod
    def upsert_resolved_source(
        *, identity: PlaybackIdentity, resolved: ResolvedPlayback
    ) -> PlaybackSource:
        source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == identity.movie_id,
                PlaybackSource.scope_key == identity.scope_key,
                PlaybackSource.provider == resolved.provider,
                PlaybackSource.provider_asset_id == resolved.provider_asset_id,
            )
        )
        if source is None and resolved.source_type == "id_catalog":
            source = db.session.scalar(
                db.select(PlaybackSource).where(
                    PlaybackSource.movie_id == identity.movie_id,
                    PlaybackSource.scope_key == identity.scope_key,
                    PlaybackSource.provider == resolved.provider,
                    PlaybackSource.source_type == resolved.source_type,
                )
            )
        if source is None:
            source = PlaybackSource(
                movie_id=identity.movie_id,
                kind=resolved.playback_mode,
                label=resolved.label,
                # Non-local rows keep a native provider reference, never an arbitrary URL.
                locator=resolved.provider_asset_id,
                season=identity.season,
                episode=identity.episode,
                provider=resolved.provider,
                source_type=resolved.source_type,
                provider_asset_id=resolved.provider_asset_id,
                scope_key=identity.scope_key,
                authorization_status="provider_catalog",
                metadata_json={"playback_mode": resolved.playback_mode, "match": resolved.match},
            )
            db.session.add(source)
        else:
            source.label = resolved.label
            source.kind = resolved.playback_mode
            source.source_type = resolved.source_type
            source.provider_asset_id = resolved.provider_asset_id
            source.locator = resolved.provider_asset_id
            source.season = identity.season
            source.episode = identity.episode
            source.metadata_json = {
                **dict(source.metadata_json or {}),
                "playback_mode": resolved.playback_mode,
                "match": resolved.match,
            }
        db.session.commit()
        return source

    @staticmethod
    def upsert_indexed_embed_source(
        *,
        movie_id: str,
        provider: str,
        provider_asset_id: str,
        label: str,
        season: int | None = None,
        episode: int | None = None,
        language: str = "",
        subtitle_languages: list[str] | None = None,
        quality: str = "",
        provenance: dict | None = None,
    ) -> PlaybackSource:
        normalized_provider = str(provider or "").strip().lower()
        normalized_asset_id = str(provider_asset_id or "").strip()
        spec = indexed_embed_provider_spec(normalized_provider)
        if not normalized_provider or not normalized_asset_id or spec is None:
            raise ValueError("Provider and provider asset ID are required.")
        if spec.key != normalized_provider:
            raise ValueError("Provider must use its canonical key.")
        if not re.fullmatch(spec.asset_id_pattern, normalized_asset_id):
            raise ValueError("Provider asset ID is invalid.")
        scoped_identity = PlaybackIdentity(
            movie_id=movie_id,
            season=season,
            episode=episode,
        )
        source = db.session.scalar(
            db.select(PlaybackSource).where(
                PlaybackSource.movie_id == movie_id,
                PlaybackSource.scope_key == scoped_identity.scope_key,
                PlaybackSource.provider == normalized_provider,
                PlaybackSource.provider_asset_id == normalized_asset_id,
            )
        )
        values = {
            "kind": "embed",
            "label": str(label or normalized_provider.title())[:300],
            "locator": normalized_asset_id,
            "season": season,
            "episode": episode,
            "source_type": "known_embed",
            "language": str(language or "")[:24],
            "subtitle_languages": list(subtitle_languages or []),
            "quality": str(quality or "")[:80],
            "provenance": dict(provenance or {"origin": "manual"}),
            "authorization_status": "manual_authorized",
            "enabled": True,
            "metadata_json": {"playback_mode": "embed"},
        }
        if source is None:
            source = PlaybackSource(
                movie_id=movie_id,
                provider=normalized_provider,
                provider_asset_id=normalized_asset_id,
                scope_key=scoped_identity.scope_key,
                **values,
            )
            db.session.add(source)
        else:
            for field, value in values.items():
                setattr(source, field, value)
        db.session.commit()
        return source

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
    def tv_episode_sources(
        movie_id: str, *, season: int, episode: int
    ) -> dict[str, PlaybackSource | None]:
        sources = _tv_episode_sources(movie_id, season=season, episode=episode)
        exact = next(
            (source for source in sources if _tv_source_scope(source)[2] == "exact_episode"),
            None,
        )
        fallback = next(
            (source for source in sources if _tv_source_scope(source)[4]),
            None,
        )
        return {"exact": exact, "fallback": fallback}

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


class ProviderAvailabilityService:
    """Current provider health only; historical metrics belong in a later table."""

    @staticmethod
    def current(source_id: str) -> ProviderAvailability | None:
        return db.session.scalar(
            db.select(ProviderAvailability).where(
                ProviderAvailability.playback_source_id == source_id
            )
        )

    @staticmethod
    def is_fresh(availability: ProviderAvailability | None, *, now=None) -> bool:
        if availability is None:
            return False
        current_time = _as_utc(now or utc_now())
        return _as_utc(availability.expires_at) >= current_time

    @staticmethod
    def record(
        source: PlaybackSource,
        result: ProviderProbeResult,
        *,
        now=None,
    ) -> ProviderAvailability:
        status = str(result.status or "UNKNOWN").upper()
        if status not in PROVIDER_AVAILABILITY_STATUSES:
            raise ValueError("Provider availability status is invalid.")
        probe_level = str(result.probe_level or "").upper()
        if probe_level not in PROVIDER_PROBE_LEVELS:
            raise ValueError("Provider availability probe level is invalid.")
        checked_at = now or utc_now()
        availability = ProviderAvailabilityService.current(source.id)
        previous_failures = availability.failure_count if availability else 0
        is_success = status == "AVAILABLE"
        # UNKNOWN means that this provider has not been verified, not that it
        # failed. Only a conclusive unavailability result increases backoff.
        if is_success:
            failure_count = 0
        elif status == "UNAVAILABLE":
            failure_count = previous_failures + 1
        else:
            failure_count = previous_failures
        ttl = ProviderAvailabilityService._ttl(status, failure_count)

        if availability is None:
            availability = ProviderAvailability(
                playback_source_id=source.id,
                expires_at=checked_at + ttl,
            )
            db.session.add(availability)
        availability.status = status
        availability.probe_level = probe_level
        availability.checked_at = checked_at
        availability.expires_at = checked_at + ttl
        availability.latency_ms = result.latency_ms
        availability.failure_reason = str(result.failure_reason or "")[:500]
        availability.failure_count = failure_count
        if is_success:
            availability.last_success_at = checked_at
        db.session.commit()
        return availability

    @staticmethod
    def revalidate_if_stale(
        source: PlaybackSource,
        *,
        identity: PlaybackIdentity,
        provider: PlaybackProvider,
        now=None,
    ) -> ProviderAvailability:
        availability = ProviderAvailabilityService.current(source.id)
        if ProviderAvailabilityService.is_fresh(availability, now=now):
            return availability
        started = perf_counter()
        result = provider.probe(identity, source=source)
        if result.latency_ms is None:
            result = ProviderProbeResult(
                status=result.status,
                probe_level=result.probe_level,
                failure_reason=result.failure_reason,
                latency_ms=round((perf_counter() - started) * 1000),
            )
        return ProviderAvailabilityService.record(source, result, now=now)

    @staticmethod
    def _ttl(status: str, failure_count: int) -> timedelta:
        if status == "AVAILABLE":
            return timedelta(hours=6)
        if status == "DEGRADED":
            return timedelta(minutes=30)
        if status == "UNKNOWN":
            return timedelta(minutes=5)
        return timedelta(minutes=min(360, 5 * (2 ** max(0, failure_count - 1))))
