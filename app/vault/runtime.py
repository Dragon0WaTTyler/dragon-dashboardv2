from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import Flask, Response, abort, current_app, g, has_request_context
from flask_login import current_user
from sqlalchemy import Engine, create_engine, insert, select

from app.auth.models import PersonalWorkspace, WorkspaceConnection
from app.extensions import db
from app.vault.crypto import decrypt_payload
from app.vault.google import (
    WORKSPACE_CACHE_FILENAME,
    DriveFile,
    GoogleOAuthClient,
    GoogleOAuthError,
    GoogleVaultConflictError,
)
from app.vault.models import WorkspaceIntegration

# ``new_id("workspace")`` uses a 32-character UUID hex suffix.  Keep a
# generous bound for legacy/imported IDs while still constraining the value
# before it is used as a filesystem path component.
_WORKSPACE_ID = re.compile(r"^workspace_[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True, slots=True)
class WorkspaceBinding:
    id: str
    owner_user_id: int
    cache_path: Path


@dataclass(slots=True)
class GoogleCacheSync:
    binding: WorkspaceBinding
    client: GoogleOAuthClient
    access_token: str
    remote: DriveFile
    initial_checksum: str


class WorkspaceRuntime:
    """Create a local cache per workspace so ORM content never shares a database."""

    def __init__(self, app: Flask):
        self.app = app
        self._engines: dict[str, Engine] = {}

    def cache_path(self, workspace_id: str) -> Path:
        if not _WORKSPACE_ID.fullmatch(workspace_id):
            raise ValueError("Invalid personal workspace identifier.")
        return Path(self.app.instance_path) / "workspaces" / workspace_id / "cache.sqlite3"

    def sync_status(self, workspace: PersonalWorkspace, *, sync_enabled: bool) -> dict[str, str]:
        """Return safe, user-facing cache state without reading credentials."""

        binding = WorkspaceBinding(
            id=workspace.id,
            owner_user_id=workspace.owner_user_id,
            cache_path=self.cache_path(workspace.id),
        )
        state = self._read_sync_state(binding)
        if bool(state.get("conflict")):
            return {
                "tone": "error",
                "label": "Sync needs attention",
                "message": (
                    "A newer Google Drive copy and unsynchronised local changes were both kept. "
                    "Resolve the conflict before continuing on this device."
                ),
            }
        if not sync_enabled:
            return {
                "tone": "warning",
                "label": "Local private cache",
                "message": "Google Drive sync is not enabled on this Dragon installation.",
            }
        if workspace.state == "needs_seed":
            return {
                "tone": "warning",
                "label": "Preparing first backup",
                "message": (
                    "Your legacy Dragon data will be copied to Google Drive on the next request."
                ),
            }
        if state.get("remote_version") and not bool(state.get("dirty")):
            return {
                "tone": "success",
                "label": "Google Drive synchronised",
                "message": "This device is using your private Google Drive workspace.",
            }
        return {
            "tone": "warning",
            "label": "Sync pending",
            "message": "Dragon will save this private workspace to Google Drive after a change.",
        }

    @staticmethod
    def _checksum(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _sync_state_path(binding: WorkspaceBinding) -> Path:
        return binding.cache_path.with_name("sync-state.json")

    def _read_sync_state(self, binding: WorkspaceBinding) -> dict[str, Any]:
        path = self._sync_state_path(binding)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_sync_state(self, binding: WorkspaceBinding, payload: dict[str, Any]) -> None:
        path = self._sync_state_path(binding)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".next")
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _checkpoint(self, binding: WorkspaceBinding) -> None:
        engine = self._engines.get(binding.id)
        if engine is None:
            return
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")

    def _replace_cache(self, binding: WorkspaceBinding, contents: bytes) -> None:
        previous = self._engines.pop(binding.id, None)
        if previous is not None:
            previous.dispose()
        binding.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = binding.cache_path.with_suffix(".incoming")
        temporary.write_bytes(contents)
        os.replace(temporary, binding.cache_path)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{binding.cache_path}{suffix}")
            if sidecar.exists():
                sidecar.unlink()

    def _seed_legacy_cache(self, binding: WorkspaceBinding) -> None:
        if db.engine.dialect.name != "sqlite":
            raise GoogleOAuthError(
                "Legacy import currently requires Dragon's SQLite database. "
                "Export a snapshot first."
            )
        source_path = db.engine.url.database
        if not source_path:
            raise GoogleOAuthError("Dragon could not locate the legacy SQLite database.")
        binding.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(source_path) as source, sqlite3.connect(binding.cache_path) as target:
            source.backup(target)

    def engine_for(self, binding: WorkspaceBinding) -> Engine:
        engine = self._engines.get(binding.id)
        if engine is not None:
            return engine
        binding.cache_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            f"sqlite:///{binding.cache_path.as_posix()}",
            connect_args={"timeout": 30},
        )
        # Importing the model above registers the portable integration table before
        # this workspace schema is materialised.
        assert WorkspaceIntegration.__table__.name == "workspace_integrations"
        db.metadata.create_all(engine)
        with engine.begin() as connection:
            owner_table = db.metadata.tables["users"]
            owner_exists = connection.scalar(
                select(owner_table.c.id).where(owner_table.c.id == binding.owner_user_id)
            )
            if owner_exists is None:
                connection.execute(
                    insert(owner_table).values(
                        id=binding.owner_user_id,
                        username=f"workspace-owner-{binding.owner_user_id}",
                        password_hash=binding.id,
                        is_active_account=True,
                    )
                )
        self._engines[binding.id] = engine
        return engine

    def bind(self, workspace: PersonalWorkspace) -> WorkspaceBinding:
        binding = WorkspaceBinding(
            id=workspace.id,
            owner_user_id=workspace.owner_user_id,
            cache_path=self.cache_path(workspace.id),
        )
        g.dragon_workspace_binding = binding
        g.dragon_workspace_engine = self.engine_for(binding)
        return binding

    def _google_client_and_token(
        self, workspace: PersonalWorkspace
    ) -> tuple[GoogleOAuthClient, str]:
        connection = db.session.scalar(
            select(WorkspaceConnection).where(
                WorkspaceConnection.workspace_id == workspace.id,
                WorkspaceConnection.provider == "google_drive",
            )
        )
        if connection is None:
            raise GoogleOAuthError("Dragon cannot find this workspace's Google Drive connection.")
        credential = decrypt_payload(
            str(self.app.config["SECRET_KEY"]),
            connection.credential_ciphertext,
        )
        refresh_token = str(credential.get("refresh_token") or "").strip()
        if not refresh_token:
            raise GoogleOAuthError("Dragon cannot reopen this Google Drive workspace.")
        injected = self.app.extensions.get("dragon_google_oauth_client")
        client = injected if injected is not None else GoogleOAuthClient(self.app.config)
        return client, client.refresh_access_token(refresh_token=refresh_token)

    def prepare_google_sync(self, workspace: PersonalWorkspace) -> WorkspaceBinding:
        binding = WorkspaceBinding(
            id=workspace.id,
            owner_user_id=workspace.owner_user_id,
            cache_path=self.cache_path(workspace.id),
        )
        client, access_token = self._google_client_and_token(workspace)
        state = self._read_sync_state(binding)
        remote = client.find_appdata_file(access_token=access_token, name=WORKSPACE_CACHE_FILENAME)
        if remote is None:
            if workspace.state == "needs_seed" and not binding.cache_path.exists():
                self._seed_legacy_cache(binding)
            self.engine_for(binding)
            self._checkpoint(binding)
            contents = binding.cache_path.read_bytes()
            remote = client.upload_appdata_file(
                access_token=access_token,
                name=WORKSPACE_CACHE_FILENAME,
                contents=contents,
            )
            state = {
                "remote_version": remote.version,
                "remote_etag": remote.etag,
                "dirty": False,
                "conflict": False,
            }
            self._write_sync_state(binding, state)
            if workspace.state == "needs_seed":
                workspace.state = "ready"
                db.session.commit()
        else:
            cached = binding.cache_path.is_file()
            needs_download = (
                not cached
                or state.get("remote_version") != remote.version
            )
            if needs_download:
                if cached and bool(state.get("dirty") or state.get("conflict")):
                    state["conflict"] = True
                    self._write_sync_state(binding, state)
                    raise GoogleVaultConflictError(
                        "This workspace has unsynchronised local changes and a newer Drive copy."
                    )
                contents, remote = client.download_appdata_file(
                    access_token=access_token,
                    file=remote,
                )
                self._replace_cache(binding, contents)
                state = {
                    "remote_version": remote.version,
                    "remote_etag": remote.etag,
                    "dirty": False,
                    "conflict": False,
                }
                self._write_sync_state(binding, state)
            else:
                remote = DriveFile(
                    id=remote.id,
                    name=remote.name,
                    version=remote.version,
                    etag=str(state["remote_etag"]),
                )
        engine = self.engine_for(binding)
        g.dragon_workspace_binding = binding
        g.dragon_workspace_engine = engine
        g.dragon_google_cache_sync = GoogleCacheSync(
            binding=binding,
            client=client,
            access_token=access_token,
            remote=remote,
            initial_checksum=self._checksum(binding.cache_path),
        )
        return binding

    def finalize_google_sync(self) -> str:
        sync = getattr(g, "dragon_google_cache_sync", None)
        if not isinstance(sync, GoogleCacheSync):
            return "not-requested"
        self._checkpoint(sync.binding)
        checksum = self._checksum(sync.binding.cache_path)
        if checksum == sync.initial_checksum:
            return "unchanged"
        state = self._read_sync_state(sync.binding)
        state["dirty"] = True
        self._write_sync_state(sync.binding, state)
        if state.get("conflict"):
            return "conflict"
        try:
            remote = sync.client.upload_appdata_file(
                access_token=sync.access_token,
                name=WORKSPACE_CACHE_FILENAME,
                contents=sync.binding.cache_path.read_bytes(),
                current=sync.remote,
            )
        except GoogleVaultConflictError:
            state["conflict"] = True
            self._write_sync_state(sync.binding, state)
            return "conflict"
        state = {
            "remote_version": remote.version,
            "remote_etag": remote.etag,
            "dirty": False,
            "conflict": False,
        }
        self._write_sync_state(sync.binding, state)
        return "saved"

    def dispose(self) -> None:
        for engine in self._engines.values():
            engine.dispose()
        self._engines.clear()


def runtime_for(app: Flask) -> WorkspaceRuntime:
    runtime = app.extensions.get("dragon_workspace_runtime")
    if not isinstance(runtime, WorkspaceRuntime):
        raise RuntimeError("Personal workspace runtime is not installed.")
    return runtime


def install_workspace_runtime(app: Flask) -> None:
    runtime = WorkspaceRuntime(app)
    app.extensions["dragon_workspace_runtime"] = runtime

    @app.before_request
    def bind_authenticated_workspace() -> None:
        if not current_user.is_authenticated:
            return
        workspace = db.session.scalar(
            select(PersonalWorkspace).where(PersonalWorkspace.owner_user_id == current_user.id)
        )
        if workspace is None or workspace.state not in {"needs_seed", "ready"}:
            return
        if app.config.get("DRAGON_GOOGLE_PERSONAL_VAULT_SYNC_ENABLED"):
            try:
                runtime.prepare_google_sync(workspace)
            except GoogleVaultConflictError:
                abort(
                    409,
                    description=(
                        "Your Google workspace changed on another device while this device "
                        "still has unsynchronised changes. Dragon preserved both copies; "
                        "resolve the conflict before continuing."
                    ),
                )
            except GoogleOAuthError as exc:
                current_app.logger.warning("Google personal vault unavailable: %s", exc)
                abort(503, description="Your private Google workspace is unavailable. Try again.")
        else:
            runtime.bind(workspace)

    @app.after_request
    def save_authenticated_workspace(response: Response) -> Response:
        if not app.config.get("DRAGON_GOOGLE_PERSONAL_VAULT_SYNC_ENABLED"):
            return response
        try:
            status = runtime.finalize_google_sync()
        except GoogleOAuthError as exc:
            current_app.logger.warning("Google personal vault save failed: %s", exc)
            response.headers["X-Dragon-Vault-Sync"] = "deferred"
            return response
        if status in {"saved", "conflict"}:
            response.headers["X-Dragon-Vault-Sync"] = status
        return response

def bind_workspace(workspace: PersonalWorkspace) -> WorkspaceBinding:
    """Bind a workspace in tests and explicit command flows."""

    if not has_request_context():
        raise RuntimeError("A request context is required to bind a personal workspace.")
    return runtime_for(current_app._get_current_object()).bind(workspace)
