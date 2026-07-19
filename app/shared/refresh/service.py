from __future__ import annotations

from flask import current_app

from app.reading.services import ReadingService
from app.shared.operations import OperationService
from app.youtube.providers import YouTubePlaylistClient, YouTubeProviderError
from app.youtube.services import YouTubeService

DOMAINS = {
    "all",
    "movies",
    "youtube_watch_later",
    "youtube_pockettube",
    "reading",
    "books",
    "chess",
}
KINDS = {"refresh", "sync", "repair", "diagnose"}


class OperationCoordinator:
    @staticmethod
    def run(*, kind: str, domain: str, scope: str = "all"):
        if kind not in KINDS:
            raise ValueError("Unknown operation kind.")
        if domain not in DOMAINS:
            raise ValueError("Unknown operation domain.")
        operation = OperationService.start(kind=kind, domain=domain, scope=scope[:120])
        if kind in {"refresh", "sync"} and domain == "youtube_watch_later":
            if not current_app.config["DRAGON_YOUTUBE_SYNC_ENABLED"]:
                return OperationService.complete(
                    operation,
                    counts={"changed": 0},
                    warnings=["YouTube playlist synchronization is not configured."],
                )
            try:
                client = current_app.extensions.get("dragon_youtube_playlist_client")
                if client is None:
                    client = YouTubePlaylistClient(current_app.config["DRAGON_YOUTUBE_API_KEY"])
                counts = YouTubeService.sync_watch_later(
                    client,
                    current_app.config["DRAGON_YOUTUBE_WATCH_LATER_PLAYLIST_ID"],
                )
            except YouTubeProviderError as exc:
                return OperationService.fail(operation, exc)
            except Exception as exc:
                return OperationService.fail(operation, exc)
            return OperationService.complete(operation, counts=counts)
        if kind in {"refresh", "sync"} and domain == "youtube_pockettube":
            if not current_app.config["DRAGON_YOUTUBE_SYNC_ENABLED"]:
                return OperationService.complete(
                    operation,
                    counts={"changed": 0},
                    warnings=["YouTube synchronization is not configured."],
                )
            export_path = YouTubeService.latest_pockettube_export()
            if export_path is None:
                return OperationService.complete(
                    operation,
                    counts={"changed": 0},
                    warnings=["No PocketTube export was found in Downloads."],
                )
            try:
                client = current_app.extensions.get("dragon_youtube_playlist_client")
                if client is None:
                    client = YouTubePlaylistClient(current_app.config["DRAGON_YOUTUBE_API_KEY"])
                counts = YouTubeService.sync_pockettube(client, export_path)
            except YouTubeProviderError as exc:
                return OperationService.fail(operation, exc)
            except Exception as exc:
                return OperationService.fail(operation, exc)
            return OperationService.complete(operation, counts=counts)
        if kind in {"refresh", "sync"} and domain == "reading":
            client = current_app.extensions.get("dragon_feed_client")
            if client is None:
                return OperationService.complete(
                    operation,
                    counts={"changed": 0},
                    warnings=["Article source synchronization is unavailable."],
                )
            try:
                counts = ReadingService.sync_sources(client)
            except Exception as exc:
                return OperationService.fail(operation, exc)
            warnings = []
            if counts["sources_failed"]:
                warnings.append(
                    f'{counts["sources_failed"]} article source(s) could not be reached. '
                    "Working sources were still updated."
                )
            return OperationService.complete(operation, counts=counts, warnings=warnings)
        if kind in {"refresh", "sync"} and not current_app.config[
            "DRAGON_EXTERNAL_SYNC_ENABLED"
        ]:
            return OperationService.complete(
                operation,
                counts={"changed": 0},
                warnings=["External synchronization is disabled; local data was not changed."],
            )
        return OperationService.complete(
            operation,
            counts={"changed": 0},
            warnings=[
                "No provider adapter is configured for this operation; local data was not changed."
            ],
        )
