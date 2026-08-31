from __future__ import annotations

import hashlib
import secrets
from typing import Any

from sqlalchemy import select

from app.auth.models import ExternalIdentity, PersonalWorkspace, User, WorkspaceConnection
from app.extensions import db
from app.shared.ids import new_id
from app.vault.crypto import decrypt_payload, encrypt_payload
from app.vault.google import GoogleOAuthClient


def _username_for_google_subject(subject: str) -> str:
    digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:32]
    return f"google-{digest}"


class GoogleWorkspaceService:
    """Create only identity/vault pointers locally; personal data stays in Drive."""

    @staticmethod
    def connect(
        *,
        client: GoogleOAuthClient,
        secret_key: str,
        token_payload: dict[str, Any],
        identity_payload: dict[str, str],
        existing_user: User | None = None,
    ) -> User:
        subject = str(identity_payload.get("subject") or "").strip()
        access_token = str(token_payload.get("access_token") or "").strip()
        if not subject or not access_token:
            raise ValueError("Google workspace identity is incomplete.")

        identity = db.session.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == "google", ExternalIdentity.subject == subject
            )
        )
        if identity is None:
            if existing_user is None:
                user = User(username=_username_for_google_subject(subject), password_hash="")
                user.set_password(secrets.token_urlsafe(48))
                db.session.add(user)
                db.session.flush()
            else:
                user = existing_user
            identity = ExternalIdentity(
                user_id=user.id,
                provider="google",
                subject=subject,
                email=str(identity_payload.get("email") or "").strip(),
                display_name=str(identity_payload.get("display_name") or "").strip(),
            )
            db.session.add(identity)
        else:
            user = db.session.get(User, identity.user_id)
            if user is None:
                raise ValueError("Google account identity has no Dragon account.")
            if existing_user is not None and user.id != existing_user.id:
                raise ValueError(
                    "This Google account is already linked to a different Dragon user."
                )
            identity.email = str(identity_payload.get("email") or "").strip()
            identity.display_name = str(identity_payload.get("display_name") or "").strip()

        workspace = db.session.scalar(
            select(PersonalWorkspace).where(PersonalWorkspace.owner_user_id == user.id)
        )
        if workspace is None:
            remote_workspace = client.locate_vault(access_token=access_token)
            if existing_user is not None and remote_workspace is not None:
                raise ValueError(
                    "This Google Drive account already has a Dragon workspace. "
                    "Sign in directly with Google instead of importing this local account."
                )
            workspace = PersonalWorkspace(
                id=remote_workspace.workspace_id if remote_workspace else new_id("workspace"),
                owner_user_id=user.id,
                state="needs_seed" if existing_user is not None else "provisioning",
            )
            db.session.add(workspace)
            db.session.flush()
            remote_workspace = remote_workspace or client.create_vault(
                access_token=access_token, workspace_id=workspace.id
            )
        else:
            remote_workspace = client.ensure_vault(
                access_token=access_token, workspace_id=workspace.id
            )
            if remote_workspace.workspace_id != workspace.id:
                raise ValueError(
                    "This Google Drive vault belongs to a different Dragon workspace. "
                    "Reconnect it from the matching Dragon account."
                )
        workspace.remote_locator = remote_workspace.file_id
        if workspace.state != "needs_seed":
            workspace.state = "ready"

        connection = db.session.scalar(
            select(WorkspaceConnection).where(
                WorkspaceConnection.workspace_id == workspace.id,
                WorkspaceConnection.provider == "google_drive",
            )
        )
        previous = (
            decrypt_payload(secret_key, connection.credential_ciphertext) if connection else {}
        )
        refresh_token = str(
            token_payload.get("refresh_token") or previous.get("refresh_token") or ""
        ).strip()
        if not refresh_token:
            raise ValueError(
                "Google did not provide a reusable connection. Start Google sign-in again."
            )
        credential = {
            "refresh_token": refresh_token,
            "google_subject": subject,
            "vault_file_id": remote_workspace.file_id,
        }
        if connection is None:
            connection = WorkspaceConnection(
                workspace_id=workspace.id,
                provider="google_drive",
                credential_ciphertext=encrypt_payload(secret_key, credential),
                scopes=sorted(str(token_payload.get("scope") or "").split()),
            )
            db.session.add(connection)
        else:
            connection.credential_ciphertext = encrypt_payload(secret_key, credential)
            connection.scopes = sorted(str(token_payload.get("scope") or "").split())
        db.session.commit()
        return user
