from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from urllib.parse import parse_qs, urlparse

from app.extensions import db
from app.history.services import HistoryService
from app.playback.identity import PlaybackIdentity
from app.playback.models import (
    MagnetCandidate,
    PlaybackAttempt,
    PlaybackProviderPreference,
    PlaybackSource,
    ProviderAvailability,
)
from app.playback.providers import (
    ID_CATALOG_EMBED_PROVIDER_SPECS,
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
PLAYBACK_ATTEMPT_OUTCOMES = {"started", "embed_ready", "success", "failure"}
AUTHORIZED_EMBED_AUTHORIZATION_STATUSES = frozenset(
    {"account_authorized", "catalog_authorized", "manual_authorized"}
)
INDEXED_EMBED_SOURCE_TYPES = frozenset({"account_catalog", "known_embed"})
DEFAULT_PROVIDER_PRIORITIES = {
    **{spec.key: spec.default_priority for spec in INDEXED_EMBED_PROVIDER_SPECS},
    **{spec.key: spec.default_priority for spec in ID_CATALOG_EMBED_PROVIDER_SPECS},
    "vidsrc": 100,
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)  # noqa: UP017 - Python 3.10 compatibility
    return value.astimezone(timezone.utc)  # noqa: UP017 - Python 3.10 compatibility


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


def _availability_presentation(availability: ProviderAvailability | None) -> dict:
    """Return recorded health only; this helper never triggers a provider probe."""

    fresh = bool(
        availability
        and _as_utc(availability.expires_at) >= _as_utc(utc_now())
    )
    return {
        "availability_status": str(availability.status) if fresh else "UNKNOWN",
        "availability_checked": availability is not None,
        "availability_fresh": fresh,
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
                # Kept as a compatibility field only; background provider
                # probing is not part of Dragon's explicit-action policy.
                "background_checks": False,
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
        """Save local provider preferences without enabling background probes.

        ``background_checks`` remains in the method signature and table for
        compatibility with existing installations, but Dragon's playback
        policy is explicit-action-only. Provider health runs only from the
        settings Test action or an explicit playback request.
        """
        provider = provider.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", provider):
            raise ValueError("Playback provider is invalid.")
        preference = db.session.get(PlaybackProviderPreference, provider)
        if preference is None:
            preference = PlaybackProviderPreference(provider=provider)
            db.session.add(preference)
        preference.enabled = bool(enabled)
        preference.priority = max(0, min(int(priority), 10_000))
        preference.background_checks = False
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
            PlaybackSource.source_type.in_(INDEXED_EMBED_SOURCE_TYPES),
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
        priorities = provider_priorities or {}
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
                    "enabled": row.enabled,
                    "source_type_label": "Authorized embed mapping",
                    "priority": (
                        row.priority_override
                        if row.priority_override is not None
                        else priorities.get(row.provider, 100)
                    ),
                    **_availability_presentation(
                        availability_by_source_id.get(row.id)
                    ),
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
        availability_by_source_id = {
            availability.playback_source_id: availability
            for availability in db.session.scalars(
                db.select(ProviderAvailability).where(
                    ProviderAvailability.playback_source_id.in_([source.id for source in sources])
                )
            )
        } if sources else {}
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
                    "enabled": source.enabled,
                    "source_type_label": "Local runtime source",
                    "priority": source.priority_override,
                    **_availability_presentation(
                        availability_by_source_id.get(source.id)
                    ),
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
        return VidSrcProvider(base_url=base_url).build_embed(identity).response_item()

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
        authorization_status: str = "manual_authorized",
        enabled: bool = True,
        source_type: str = "known_embed",
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
        if authorization_status not in AUTHORIZED_EMBED_AUTHORIZATION_STATUSES:
            raise ValueError("Indexed embed source authorization status is invalid.")
        if source_type not in INDEXED_EMBED_SOURCE_TYPES:
            raise ValueError("Indexed embed source type is invalid.")
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
            "source_type": source_type,
            "language": str(language or "")[:24],
            "subtitle_languages": list(subtitle_languages or []),
            "quality": str(quality or "")[:80],
            "provenance": dict(provenance or {"origin": "manual"}),
            "authorization_status": authorization_status,
            "enabled": bool(enabled),
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


class PlaybackAttemptService:
    """Persist explicit player lifecycle observations for future source memory."""

    @staticmethod
    def record(
        *,
        user_id: int | str,
        movie_id: str,
        provider: str,
        content_id: str,
        scope_key: str,
        client_attempt_id: str,
        outcome: str,
        playback_source_id: str | None = None,
        server_id: str = "",
        device_id: str = "",
        startup_ms: int | None = None,
        quality: str = "",
        language: str = "",
        failure_reason: str = "",
    ) -> PlaybackAttempt:
        try:
            normalized_user_id = int(user_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Playback attempt user is invalid.") from exc
        normalized_provider = str(provider or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", normalized_provider):
            raise ValueError("Playback attempt provider is invalid.")
        normalized_content_id = str(content_id or "").strip()
        normalized_scope = str(scope_key or "").strip().lower()
        normalized_attempt_id = str(client_attempt_id or "").strip()
        if not normalized_content_id or len(normalized_content_id) > 96:
            raise ValueError("Playback attempt content is invalid.")
        if not re.fullmatch(r"(?:movie|s\d{2}e\d{2})", normalized_scope):
            raise ValueError("Playback attempt scope is invalid.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", normalized_attempt_id):
            raise ValueError("Playback attempt ID is invalid.")
        normalized_outcome = str(outcome or "").strip().lower()
        if normalized_outcome not in PLAYBACK_ATTEMPT_OUTCOMES:
            raise ValueError("Playback attempt outcome is invalid.")

        normalized_source_id = str(playback_source_id or "").strip() or None
        normalized_server_id = str(server_id or "").strip()[:120]
        normalized_device_id = str(device_id or "").strip()[:128]
        normalized_quality = str(quality or "").strip()[:80]
        normalized_language = str(language or "").strip().lower()[:24]
        normalized_failure_reason = str(failure_reason or "").strip()[:500]
        if startup_ms is None or startup_ms == "":
            normalized_startup_ms = None
        else:
            try:
                normalized_startup_ms = int(startup_ms)
            except (TypeError, ValueError) as exc:
                raise ValueError("Playback attempt startup time is invalid.") from exc
            if normalized_startup_ms < 0 or normalized_startup_ms > 86_400_000:
                raise ValueError("Playback attempt startup time is invalid.")

        attempt = db.session.scalar(
            db.select(PlaybackAttempt).where(
                PlaybackAttempt.user_id == normalized_user_id,
                PlaybackAttempt.client_attempt_id == normalized_attempt_id,
            )
        )
        if attempt is None:
            attempt = PlaybackAttempt(
                user_id=normalized_user_id,
                movie_id=movie_id,
                playback_source_id=normalized_source_id,
                provider=normalized_provider,
                server_id=normalized_server_id,
                content_id=normalized_content_id,
                scope_key=normalized_scope,
                device_id=normalized_device_id,
                client_attempt_id=normalized_attempt_id,
                outcome=normalized_outcome,
                success=(
                    True
                    if normalized_outcome == "success"
                    else False
                    if normalized_outcome == "failure"
                    else None
                ),
                startup_ms=normalized_startup_ms,
                quality=normalized_quality,
                language=normalized_language,
                failure_reason=normalized_failure_reason,
            )
            db.session.add(attempt)
        else:
            if (
                attempt.movie_id != movie_id
                or attempt.provider != normalized_provider
                or attempt.scope_key != normalized_scope
            ):
                raise ValueError("Playback attempt ID is already used for another playback.")
            if attempt.outcome in {"success", "failure"} and normalized_outcome != attempt.outcome:
                return attempt
            attempt.playback_source_id = normalized_source_id or attempt.playback_source_id
            attempt.server_id = normalized_server_id or attempt.server_id
            attempt.device_id = normalized_device_id or attempt.device_id
            attempt.outcome = normalized_outcome
            attempt.success = (
                True
                if normalized_outcome == "success"
                else False
                if normalized_outcome == "failure"
                else None
            )
            if normalized_startup_ms is not None:
                attempt.startup_ms = normalized_startup_ms
            attempt.quality = normalized_quality or attempt.quality
            attempt.language = normalized_language or attempt.language
            if normalized_failure_reason:
                attempt.failure_reason = normalized_failure_reason
        db.session.commit()
        return attempt

    @staticmethod
    def recent_summary(*, user_id: int | str, provider: str | None = None) -> dict[str, dict]:
        try:
            normalized_user_id = int(user_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Playback attempt user is invalid.") from exc
        query = db.select(PlaybackAttempt).where(PlaybackAttempt.user_id == normalized_user_id)
        normalized_provider = str(provider or "").strip().lower()
        if normalized_provider:
            query = query.where(PlaybackAttempt.provider == normalized_provider)
        rows = list(
            db.session.scalars(query.order_by(PlaybackAttempt.created_at.desc()).limit(500))
        )
        summaries: dict[str, dict] = {}
        for row in rows:
            summary = summaries.setdefault(
                row.provider,
                {
                    "provider": row.provider,
                    "attempts": 0,
                    "successes": 0,
                    "failures": 0,
                    "avg_startup_ms": None,
                    "last_success_at": None,
                },
            )
            summary["attempts"] += 1
            if row.success is True:
                summary["successes"] += 1
            elif row.success is False:
                summary["failures"] += 1
            if row.startup_ms is not None:
                values = summary.setdefault("_startup_values", [])
                values.append(row.startup_ms)
            if row.success is True and summary["last_success_at"] is None:
                summary["last_success_at"] = row.created_at.isoformat()
        for summary in summaries.values():
            values = summary.pop("_startup_values", [])
            if values:
                summary["avg_startup_ms"] = round(sum(values) / len(values))
        return summaries

    @staticmethod
    def last_good_server_id(
        *,
        user_id: int | str,
        provider: str,
        movie_id: str | None = None,
        scope_key: str | None = None,
    ) -> str:
        """Return a provider-supplied opaque server identity from success history."""
        try:
            normalized_user_id = int(user_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Playback attempt user is invalid.") from exc
        normalized_provider = str(provider or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", normalized_provider):
            raise ValueError("Playback attempt provider is invalid.")

        filters = [
            PlaybackAttempt.user_id == normalized_user_id,
            PlaybackAttempt.provider == normalized_provider,
            PlaybackAttempt.success.is_(True),
            PlaybackAttempt.server_id != "",
        ]
        if movie_id is not None:
            filters.append(PlaybackAttempt.movie_id == str(movie_id).strip())
        if scope_key is not None:
            normalized_scope = str(scope_key or "").strip().lower()
            if not re.fullmatch(r"(?:movie|s\d{2}e\d{2})", normalized_scope):
                raise ValueError("Playback attempt scope is invalid.")
            filters.append(PlaybackAttempt.scope_key == normalized_scope)
        return str(
            db.session.scalar(
                db.select(PlaybackAttempt.server_id)
                .where(*filters)
                .order_by(PlaybackAttempt.created_at.desc())
                .limit(1)
            )
            or ""
        )

    @staticmethod
    def provider_scores(
        *,
        user_id: int | str,
        movie_id: str,
        scope_key: str,
        provider_keys: set[str] | frozenset[str],
        preferred_language: str = "",
        preferred_quality: str = "",
        metadata_capabilities: dict[str, dict[str, bool]] | None = None,
        source_metadata: dict[str, list[dict[str, object]]] | None = None,
    ) -> dict[str, dict]:
        """Score already-known providers using local playback history only.

        Language and quality preferences are applied only for providers whose
        registered capabilities explicitly cover the corresponding metadata.
        """
        keys = {
            str(key).strip().lower()
            for key in provider_keys
            if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", str(key).strip().lower())
        }
        if not keys:
            return {}
        try:
            normalized_user_id = int(user_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Playback attempt user is invalid.") from exc
        rows = list(
            db.session.scalars(
                db.select(PlaybackAttempt)
                .where(
                    PlaybackAttempt.user_id == normalized_user_id,
                    PlaybackAttempt.provider.in_(keys),
                )
                .order_by(PlaybackAttempt.created_at.desc())
                .limit(1000)
            )
        )
        now = _as_utc(utc_now())
        normalized_language = str(preferred_language or "").strip().lower()
        normalized_quality = str(preferred_quality or "").strip().lower()
        quality_rank = {
            "360p": 1,
            "480p": 2,
            "576p": 3,
            "720p": 4,
            "1080p": 5,
            "1440p": 6,
            "2160p": 7,
        }
        capability_map = {
            str(key).strip().lower(): dict(value or {})
            for key, value in (metadata_capabilities or {}).items()
        }
        source_metadata_map = {
            str(key).strip().lower(): [
                dict(item) for item in value if isinstance(item, dict)
            ]
            for key, value in (source_metadata or {}).items()
            if isinstance(value, list)
        }
        reliable_quality_rows = [
            row
            for row in rows
            if row.provider in keys
            and capability_map.get(row.provider, {}).get("quality")
            and row.success is True
        ]
        best_quality_rank = max(
            (
                quality_rank.get(str(row.quality or "").strip().lower(), 0)
                for row in reliable_quality_rows
            ),
            default=0,
        )
        reliable_quality_values = [
            str(item.get("quality") or "").strip().lower()
            for key, metadata_rows in source_metadata_map.items()
            if capability_map.get(key, {}).get("quality")
            for item in metadata_rows
            if str(item.get("quality") or "").strip()
        ]
        best_quality_rank = max(
            [
                best_quality_rank,
                *[quality_rank.get(value, 0) for value in reliable_quality_values],
            ],
            default=0,
        )
        scores: dict[str, dict] = {}
        for key in keys:
            provider_rows = [row for row in rows if row.provider == key]
            final_rows = [row for row in provider_rows if row.success is not None]
            successes = sum(row.success is True for row in final_rows)
            failures = sum(row.success is False for row in final_rows)
            startup_values = [row.startup_ms for row in provider_rows if row.startup_ms is not None]
            title_successes = sum(
                row.success is True
                and row.movie_id == movie_id
                and row.scope_key == scope_key
                for row in provider_rows
            )
            provider_capabilities = capability_map.get(key, {})
            current_source_metadata = source_metadata_map.get(key, [])
            language_matches = 0
            if (
                normalized_language
                and normalized_language != "auto"
                and provider_capabilities.get("language")
            ):
                language_matches = sum(
                    row.success is True
                    and str(row.language or "").strip().lower() == normalized_language
                    for row in provider_rows
                )
                language_matches += sum(
                    str(item.get("language") or "").strip().lower() == normalized_language
                    for item in current_source_metadata
                )
            quality_matches = 0
            if normalized_quality not in {"", "auto"} and provider_capabilities.get("quality"):
                if normalized_quality == "best":
                    quality_matches = sum(
                        row.success is True
                        and quality_rank.get(
                            str(row.quality or "").strip().lower(), 0
                        ) == best_quality_rank
                        and best_quality_rank > 0
                        for row in provider_rows
                    )
                    quality_matches += sum(
                        quality_rank.get(str(item.get("quality") or "").strip().lower(), 0)
                        == best_quality_rank
                        and best_quality_rank > 0
                        for item in current_source_metadata
                    )
                else:
                    quality_matches = sum(
                        row.success is True
                        and str(row.quality or "").strip().lower() == normalized_quality
                        for row in provider_rows
                    )
                    quality_matches += sum(
                        str(item.get("quality") or "").strip().lower() == normalized_quality
                        for item in current_source_metadata
                    )
            success_rate = successes / len(final_rows) if final_rows else 0.0
            avg_startup = (
                round(sum(startup_values) / len(startup_values)) if startup_values else None
            )
            recent_success_bonus = 0.0
            for row in provider_rows:
                if row.success is not True:
                    continue
                age_hours = max(0.0, (now - _as_utc(row.created_at)).total_seconds() / 3600)
                recent_success_bonus = max(0.0, 10.0 - min(10.0, age_hours / 6.0))
                break
            startup_bonus = (
                max(0.0, 20.0 - min(20.0, avg_startup / 250.0))
                if avg_startup is not None
                else 0.0
            )
            score = (
                (success_rate * 60.0)
                + min(20.0, successes * 2.0)
                + min(20.0, title_successes * 5.0)
                + startup_bonus
                + recent_success_bonus
                + min(10.0, language_matches * 2.0)
                + min(10.0, quality_matches * 2.0)
            )
            scores[key] = {
                "provider": key,
                "score": round(score, 3),
                "successes": successes,
                "failures": failures,
                "success_rate": round(success_rate, 4),
                "avg_startup_ms": avg_startup,
                "title_successes": title_successes,
                "language_matches": language_matches,
                "quality_matches": quality_matches,
            }
        return scores
