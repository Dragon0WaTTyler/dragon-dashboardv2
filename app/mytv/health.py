from __future__ import annotations

import hashlib
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from urllib.parse import urlsplit

from flask import Flask
from sqlalchemy import func, select

from app.extensions import db
from app.mytv.cache import query_cache
from app.mytv.models import (
    TVChannel,
    TVChannelHealth,
    TVChannelRepresentative,
    TVGroup,
    TVPlaylist,
    TVTheme,
)
from app.mytv.streaming import (
    mark_stream_failure,
    mark_stream_success,
    stream_failure_penalty,
    validate_stream_url,
)

HEALTH_WORKERS = 8
HEALTH_HOST_LIMIT = 3
HEALTH_TIMEOUT_SECONDS = 7
HEALTH_CANDIDATE_LIMIT = 3
HEALTH_COMMIT_BATCH = 20

_host_limiters: dict[str, threading.BoundedSemaphore] = {}
_host_limiters_lock = threading.Lock()


@dataclass(frozen=True)
class HealthTarget:
    preference_key: str
    candidates: tuple[str, ...]


@dataclass(frozen=True)
class HealthResult:
    preference_key: str
    online: bool
    latency_ms: int | None
    source_fingerprint: str
    error: str


def _host_limiter(url: str) -> threading.BoundedSemaphore:
    hostname = urlsplit(url).hostname or "unknown"
    with _host_limiters_lock:
        return _host_limiters.setdefault(
            hostname, threading.BoundedSemaphore(HEALTH_HOST_LIMIT)
        )


def _resolve_ffprobe() -> str:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is required for accurate channel health checks.")
    return ffprobe


def _probe_url(ffprobe: str, url: str) -> bool:
    validate_stream_url(url)
    timeout_microseconds = HEALTH_TIMEOUT_SECONDS * 1_000_000
    with _host_limiter(url):
        result = subprocess.run(  # noqa: S603 - trusted ffprobe path; URL validated
            [
                ffprobe,
                "-v",
                "error",
                "-rw_timeout",
                str(timeout_microseconds),
                "-user_agent",
                "Mozilla/5.0 (Dragon My TV Health Check)",
                "-analyzeduration",
                "1000000",
                "-probesize",
                "1000000",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=HEALTH_TIMEOUT_SECONDS + 2,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    stream_types = {line.strip() for line in result.stdout.splitlines()}
    return result.returncode == 0 and bool(stream_types & {"audio", "video"})


def _probe_target(ffprobe: str, target: HealthTarget) -> HealthResult:
    started = perf_counter()
    for url in target.candidates[:HEALTH_CANDIDATE_LIMIT]:
        try:
            if _probe_url(ffprobe, url):
                mark_stream_success(url)
                return HealthResult(
                    preference_key=target.preference_key,
                    online=True,
                    latency_ms=round((perf_counter() - started) * 1000),
                    source_fingerprint=hashlib.sha256(
                        url.encode("utf-8", "ignore")
                    ).hexdigest(),
                    error="",
                )
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError):
            pass
        mark_stream_failure(url)
    return HealthResult(
        preference_key=target.preference_key,
        online=False,
        latency_ms=None,
        source_fingerprint="",
        error="All source copies failed.",
    )


class TVHealthCoordinator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = {
            "state": "idle",
            "message": "Health check ready",
            "current": 0,
            "total": 0,
            "online": 0,
            "offline": 0,
            "error": None,
            "theme_id": None,
        }

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def start(self, app: Flask, theme_id: int | None = None) -> bool:
        with self._lock:
            if self._status["state"] == "running":
                return False
            self._status.update(
                state="running",
                message="Finding enabled channels…",
                current=0,
                total=0,
                online=0,
                offline=0,
                error=None,
                theme_id=theme_id,
            )
        threading.Thread(
            target=self._run,
            args=(app, theme_id),
            daemon=True,
            name="dragon-tv-health",
        ).start()
        return True

    def _run(self, app: Flask, theme_id: int | None) -> None:
        with app.app_context():
            try:
                ffprobe = _resolve_ffprobe()
                targets = self._load_targets(theme_id)
                with self._lock:
                    self._status.update(
                        total=len(targets),
                        message=(
                            "No enabled channels need checking"
                            if not targets
                            else f"Checking {len(targets):,} enabled channels…"
                        ),
                    )
                online = 0
                offline = 0
                pending = 0
                with ThreadPoolExecutor(max_workers=HEALTH_WORKERS) as executor:
                    futures = [
                        executor.submit(_probe_target, ffprobe, target)
                        for target in targets
                    ]
                    for index, future in enumerate(as_completed(futures), start=1):
                        result = future.result()
                        with db.session.no_autoflush:
                            health = db.session.get(
                                TVChannelHealth, result.preference_key
                            )
                        if health is None:
                            health = TVChannelHealth(
                                preference_key=result.preference_key
                            )
                            db.session.add(health)
                        health.status = "online" if result.online else "offline"
                        health.checked_at = datetime.now(UTC)
                        health.latency_ms = result.latency_ms
                        health.source_fingerprint = result.source_fingerprint
                        health.failure_count = (
                            0
                            if result.online
                            else (health.failure_count or 0) + 1
                        )
                        health.last_error = result.error
                        online += int(result.online)
                        offline += int(not result.online)
                        pending += 1
                        if pending >= HEALTH_COMMIT_BATCH:
                            db.session.commit()
                            query_cache.invalidate()
                            pending = 0
                        with self._lock:
                            self._status.update(
                                current=index,
                                online=online,
                                offline=offline,
                                message=f"Checked {index:,} of {len(targets):,}",
                            )
                if pending:
                    db.session.commit()
                    query_cache.invalidate()
                with self._lock:
                    self._status.update(
                        state="complete",
                        message=f"{online:,} online · {offline:,} unavailable",
                    )
            except Exception as error:
                db.session.rollback()
                with self._lock:
                    self._status.update(
                        state="error",
                        message="Channel health check failed",
                        error=str(error)[:240],
                    )

    @staticmethod
    def _load_targets(theme_id: int | None) -> list[HealthTarget]:
        effective = func.coalesce(
            TVChannel.enabled_override, TVTheme.channel_policy, TVTheme.enabled
        ).is_(True)
        conditions = [
            TVPlaylist.imported.is_(True),
            TVPlaylist.available.is_(True),
            effective,
        ]
        if theme_id is not None:
            conditions.append(TVGroup.theme_id == theme_id)
        representative_rows = list(
            db.session.execute(
                select(
                    TVChannelRepresentative.preference_key,
                    TVChannelRepresentative.channel_id,
                )
                .join(
                    TVChannel,
                    TVChannel.id == TVChannelRepresentative.channel_id,
                )
                .join(TVGroup, TVGroup.id == TVChannel.group_id)
                .join(TVTheme, TVTheme.id == TVGroup.theme_id)
                .join(TVPlaylist, TVPlaylist.id == TVChannel.playlist_id)
                .where(*conditions)
            )
        )
        representative_ids = {
            str(row.preference_key): int(row.channel_id)
            for row in representative_rows
        }
        candidates: dict[str, list[TVChannel]] = {
            key: [] for key in representative_ids
        }
        keys = list(representative_ids)
        for offset in range(0, len(keys), 400):
            chunk = keys[offset : offset + 400]
            for channel in db.session.scalars(
                select(TVChannel)
                .join(TVPlaylist, TVPlaylist.id == TVChannel.playlist_id)
                .where(
                    TVChannel.preference_key.in_(chunk),
                    TVPlaylist.imported.is_(True),
                    TVPlaylist.available.is_(True),
                )
                .order_by(TVChannel.id.desc())
            ):
                candidates[channel.preference_key].append(channel)
        targets: list[HealthTarget] = []
        for key, rows in candidates.items():
            unique: dict[str, TVChannel] = {}
            for row in rows:
                unique.setdefault(row.stream_url, row)
            ordered = sorted(
                unique.values(),
                key=lambda row: (
                    stream_failure_penalty(row.stream_url),
                    0 if row.id == representative_ids[key] else 1,
                    -row.id,
                ),
            )
            targets.append(
                HealthTarget(
                    preference_key=key,
                    candidates=tuple(
                        row.stream_url for row in ordered[:HEALTH_CANDIDATE_LIMIT]
                    ),
                )
            )
        return targets


health_coordinator = TVHealthCoordinator()


def record_channel_health(
    preference_key: str,
    *,
    online: bool,
    source_url: str = "",
    error: str = "",
) -> None:
    health = db.session.get(TVChannelHealth, preference_key)
    if health is None:
        health = TVChannelHealth(preference_key=preference_key, failure_count=0)
        db.session.add(health)
    health.status = "online" if online else "offline"
    health.checked_at = datetime.now(UTC)
    health.latency_ms = None
    health.source_fingerprint = (
        hashlib.sha256(source_url.encode("utf-8", "ignore")).hexdigest()
        if source_url
        else ""
    )
    health.failure_count = 0 if online else (health.failure_count or 0) + 1
    health.last_error = "" if online else error[:240]
    db.session.commit()
    query_cache.invalidate()
