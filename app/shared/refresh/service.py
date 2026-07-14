from __future__ import annotations

from flask import current_app

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
