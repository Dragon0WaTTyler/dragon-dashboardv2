from __future__ import annotations

import logging
import threading
from datetime import timedelta, timezone
from time import sleep

from flask import Flask

from app.extensions import db
from app.shared.models import SnapshotRecord
from app.shared.time import utc_now

LOGGER = logging.getLogger(__name__)
# A PocketTube refresh queries each subscribed channel.  Keeping it daily stays
# comfortably within the standard YouTube Data API daily quota for large libraries.
POCKETTUBE_AUTO_SYNC_INTERVAL_SECONDS = 24 * 60 * 60
READING_AUTO_SYNC_INTERVAL_SECONDS = 5 * 60
_CHECK_INTERVAL_SECONDS = 60
_sync_lock = threading.Lock()


def start_auto_sync(app: Flask) -> None:
    if app.config.get("TESTING"):
        return
    if app.extensions.get("dragon_auto_sync_started"):
        return
    app.extensions["dragon_auto_sync_started"] = True
    thread = threading.Thread(
        target=_auto_sync_loop,
        args=(app,),
        name="dragon-auto-sync",
        daemon=True,
    )
    app.extensions["dragon_auto_sync_thread"] = thread
    thread.start()


def _auto_sync_loop(app: Flask) -> None:
    sleep(_CHECK_INTERVAL_SECONDS)
    while True:
        _sync_pockettube_if_due(app)
        _sync_reading_if_due(app)
        _sync_tv_sources_if_due(app)
        _sync_epg_if_due(app)
        sleep(_CHECK_INTERVAL_SECONDS)


def _sync_pockettube_if_due(app: Flask) -> None:
    if not _sync_lock.acquire(blocking=False):
        return
    try:
        with app.app_context():
            if not app.config.get("DRAGON_YOUTUBE_SYNC_ENABLED"):
                return
            if not _pockettube_sync_due():
                return
            from app.shared.refresh import OperationCoordinator

            operation = OperationCoordinator.run(kind="sync", domain="youtube_pockettube")
            if operation.status == "failed":
                LOGGER.warning("PocketTube auto sync failed: %s", operation.safe_error)
            else:
                LOGGER.info("PocketTube auto sync completed: %s", operation.counts)
    except Exception:
        LOGGER.exception("PocketTube auto sync crashed.")
    finally:
        _sync_lock.release()


def _pockettube_sync_due() -> bool:
    return _snapshot_sync_due(
        "youtube_pockettube",
        seconds=POCKETTUBE_AUTO_SYNC_INTERVAL_SECONDS,
    )


def _sync_reading_if_due(app: Flask) -> None:
    if not _sync_lock.acquire(blocking=False):
        return
    try:
        with app.app_context():
            from app.reading.source_manager import ReadingSourceManager

            source_ids = ReadingSourceManager.due_source_ids()
            if not source_ids:
                return
            from app.shared.refresh import OperationCoordinator

            operation = OperationCoordinator.run(
                kind="sync", domain="reading", source_ids=source_ids
            )
            if operation.status == "failed":
                LOGGER.warning("Reading auto sync failed: %s", operation.safe_error)
            else:
                LOGGER.info("Reading auto sync completed: %s", operation.counts)
    except Exception:
        LOGGER.exception("Reading auto sync crashed.")
    finally:
        _sync_lock.release()


def _sync_tv_sources_if_due(app: Flask) -> None:
    if not _sync_lock.acquire(blocking=False):
        return
    try:
        with app.app_context():
            from app.mytv.source_manager import TVSourceManager

            manager = TVSourceManager()
            for source in manager.due_sources():
                try:
                    result = manager.sync(source)
                    LOGGER.info("TV source %s auto refreshed: %s", source.name, result)
                except Exception:
                    LOGGER.exception("TV source %s auto refresh failed.", source.name)
    except Exception:
        LOGGER.exception("TV source auto sync crashed.")
    finally:
        _sync_lock.release()


def _sync_epg_if_due(app: Flask) -> None:
    if not _sync_lock.acquire(blocking=False):
        return
    try:
        with app.app_context():
            from app.mytv.epg import EPGSyncService

            if not EPGSyncService.is_due():
                return
            result = EPGSyncService().sync()
            LOGGER.info("Favorite TV guide auto refresh completed: %s", result)
    except Exception:
        LOGGER.exception("Favorite TV guide auto refresh failed.")
    finally:
        _sync_lock.release()


def _reading_sync_due() -> bool:
    return _snapshot_sync_due("reading", seconds=READING_AUTO_SYNC_INTERVAL_SECONDS)


def _snapshot_sync_due(domain: str, *, seconds: int) -> bool:
    snapshot = db.session.scalar(db.select(SnapshotRecord).where(SnapshotRecord.domain == domain))
    if snapshot is None or snapshot.last_success_at is None:
        return True
    last_success_at = snapshot.last_success_at
    if last_success_at.tzinfo is None:
        last_success_at = last_success_at.replace(tzinfo=timezone.utc)
    return utc_now() - last_success_at >= timedelta(seconds=seconds)
