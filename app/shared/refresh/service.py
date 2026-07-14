from __future__ import annotations

from flask import current_app

from app.shared.operations import OperationService

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
