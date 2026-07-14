from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.shared.time import utc_iso

DOMAIN_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")


@dataclass(frozen=True, slots=True)
class SnapshotRead:
    domain: str
    state: str
    schema_version: str | None
    generated_at: str | None
    payload: dict[str, Any] | list[Any] | None
    checksum: str | None
    message: str
    used_previous: bool = False


class SnapshotStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _paths(self, domain: str) -> tuple[Path, Path]:
        if not DOMAIN_PATTERN.fullmatch(domain):
            raise ValueError("Snapshot domain must be a safe lowercase identifier.")
        return self.root / f"{domain}.json", self.root / f"{domain}.previous.json"

    @staticmethod
    def _serialize(envelope: Mapping[str, Any]) -> bytes:
        return (json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")

    def write(
        self,
        domain: str,
        payload: dict[str, Any] | list[Any],
        *,
        schema_version: str,
    ) -> dict[str, str]:
        if not schema_version.strip():
            raise ValueError("Snapshot schema_version is required.")
        target, previous = self._paths(domain)
        envelope = {
            "schema_version": schema_version,
            "generated_at": utc_iso(),
            "payload": payload,
        }
        serialized = self._serialize(envelope)
        checksum = hashlib.sha256(serialized).hexdigest()

        if target.exists():
            shutil.copy2(target, previous)

        fd, temporary_name = tempfile.mkstemp(prefix=f".{domain}-", suffix=".tmp", dir=self.root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        return {
            "relative_path": target.name,
            "checksum": checksum,
            "generated_at": str(envelope["generated_at"]),
            "schema_version": schema_version,
        }

    @staticmethod
    def _read_path(
        path: Path,
        *,
        domain: str,
        expected_schema: str | None,
        validator: Callable[[Any], bool] | None,
    ) -> SnapshotRead:
        serialized = path.read_bytes()
        checksum = hashlib.sha256(serialized).hexdigest()
        envelope = json.loads(serialized.decode("utf-8-sig"))
        if not isinstance(envelope, dict):
            raise ValueError("Snapshot envelope must be an object.")
        schema_version = str(envelope.get("schema_version") or "")
        generated_at = str(envelope.get("generated_at") or "")
        payload = envelope.get("payload")
        if expected_schema and schema_version != expected_schema:
            raise ValueError("Snapshot schema version does not match.")
        if not isinstance(payload, (dict, list)):
            raise ValueError("Snapshot payload must be an object or list.")
        if validator and not validator(payload):
            raise ValueError("Snapshot payload failed validation.")
        return SnapshotRead(
            domain=domain,
            state="fresh",
            schema_version=schema_version,
            generated_at=generated_at,
            payload=payload,
            checksum=checksum,
            message="Using the latest local snapshot.",
        )

    def read(
        self,
        domain: str,
        *,
        expected_schema: str | None = None,
        validator: Callable[[Any], bool] | None = None,
    ) -> SnapshotRead:
        target, previous = self._paths(domain)
        if not target.exists():
            return SnapshotRead(
                domain=domain,
                state="missing",
                schema_version=None,
                generated_at=None,
                payload=None,
                checksum=None,
                message="No local snapshot is available yet.",
            )
        try:
            return self._read_path(
                target,
                domain=domain,
                expected_schema=expected_schema,
                validator=validator,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            if previous.exists():
                try:
                    fallback = self._read_path(
                        previous,
                        domain=domain,
                        expected_schema=expected_schema,
                        validator=validator,
                    )
                    return SnapshotRead(
                        domain=domain,
                        state="stale",
                        schema_version=fallback.schema_version,
                        generated_at=fallback.generated_at,
                        payload=fallback.payload,
                        checksum=fallback.checksum,
                        message="The latest snapshot is invalid; using the previous valid copy.",
                        used_previous=True,
                    )
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                    pass
            return SnapshotRead(
                domain=domain,
                state="malformed",
                schema_version=None,
                generated_at=None,
                payload=None,
                checksum=None,
                message="The local snapshot is malformed and no valid fallback exists.",
            )
