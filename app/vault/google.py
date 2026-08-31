from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

import requests

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
GOOGLE_DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
GOOGLE_SCOPES = (
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/drive.appdata",
)
VAULT_FILENAME = "dragon-workspace-v1.json"


class GoogleOAuthError(ValueError):
    """A user-safe Google authorization or Drive bootstrap error."""


@dataclass(frozen=True, slots=True)
class VaultReference:
    file_id: str
    workspace_id: str


@dataclass(frozen=True, slots=True)
class VaultDocument:
    reference: VaultReference
    payload: dict[str, Any]
    etag: str


class GoogleVaultConflictError(GoogleOAuthError):
    """The remote vault changed and must be read again before writing."""


class GoogleOAuthClient:
    def __init__(self, config: Mapping[str, Any], *, http: requests.Session | Any | None = None):
        self.client_id = str(config.get("DRAGON_GOOGLE_OAUTH_CLIENT_ID") or "").strip()
        self.client_secret = str(config.get("DRAGON_GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()
        self.configured_redirect_uri = str(
            config.get("DRAGON_GOOGLE_OAUTH_REDIRECT_URI") or ""
        ).strip()
        self.http = http or requests.Session()

    def _require_config(self) -> None:
        if not self.client_id or not self.client_secret:
            raise GoogleOAuthError("Google sign-in is not configured yet.")

    def redirect_uri(self, fallback: str) -> str:
        return self.configured_redirect_uri or fallback

    def authorization_url(self, *, redirect_uri: str, state: str) -> str:
        self._require_config()
        parameters = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(GOOGLE_SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{GOOGLE_AUTHORIZATION_URL}?{urlencode(parameters)}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> dict[str, Any]:
        self._require_config()
        if not code.strip():
            raise GoogleOAuthError("Google did not return an authorization code.")
        response = self.http.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
        if not getattr(response, "ok", False):
            raise GoogleOAuthError("Google could not complete the connection. Try again.")
        payload = response.json()
        if not isinstance(payload, dict) or not str(payload.get("access_token") or "").strip():
            raise GoogleOAuthError("Google returned an incomplete connection response.")
        return payload

    def identity(self, *, access_token: str) -> dict[str, str]:
        response = self.http.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        if not getattr(response, "ok", False):
            raise GoogleOAuthError("Google could not verify this account. Try again.")
        payload = response.json()
        subject = str(payload.get("sub") or "").strip() if isinstance(payload, dict) else ""
        if not subject:
            raise GoogleOAuthError("Google did not return a stable account identity.")
        return {
            "subject": subject,
            "email": str(payload.get("email") or "").strip(),
            "display_name": str(payload.get("name") or "").strip(),
        }

    def refresh_access_token(self, *, refresh_token: str) -> str:
        self._require_config()
        response = self.http.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
        payload = response.json() if getattr(response, "ok", False) else None
        access_token = (
            str(payload.get("access_token") or "").strip() if isinstance(payload, dict) else ""
        )
        if not access_token:
            raise GoogleOAuthError("Dragon could not reopen your Google Drive workspace.")
        return access_token

    @staticmethod
    def _headers(*, access_token: str, etag: str = "") -> dict[str, str]:
        headers = {"Authorization": f"Bearer {access_token}"}
        if etag:
            headers["If-Match"] = etag
        return headers

    def _download_vault(self, *, access_token: str, file_id: str) -> VaultDocument:
        response = self.http.get(
            f"{GOOGLE_DRIVE_FILES_URL}/{quote(file_id, safe='')}",
            headers=self._headers(access_token=access_token),
            params={"alt": "media"},
            timeout=20,
        )
        if not getattr(response, "ok", False):
            raise GoogleOAuthError("Dragon could not read your private Google Drive workspace.")
        payload = response.json()
        workspace_id = (
            str(payload.get("workspace_id") or "").strip() if isinstance(payload, dict) else ""
        )
        if not workspace_id.startswith("workspace_"):
            raise GoogleOAuthError("Your Google Drive workspace is not a valid Dragon vault.")
        headers = getattr(response, "headers", {})
        etag = str(headers.get("ETag") or headers.get("etag") or "")
        return VaultDocument(
            reference=VaultReference(file_id=file_id, workspace_id=workspace_id),
            payload=payload,
            etag=etag,
        )

    def locate_vault(self, *, access_token: str) -> VaultReference | None:
        response = self.http.get(
            GOOGLE_DRIVE_FILES_URL,
            headers=self._headers(access_token=access_token),
            params={
                "spaces": "appDataFolder",
                "q": f"name = '{VAULT_FILENAME}' and trashed = false",
                "fields": "files(id,name)",
            },
            timeout=20,
        )
        if not getattr(response, "ok", False):
            raise GoogleOAuthError("Dragon could not open your private Google Drive workspace.")
        payload = response.json()
        files = payload.get("files", []) if isinstance(payload, dict) else []
        file_id = str(files[0].get("id") or "").strip() if files else ""
        if not file_id:
            return None
        return self._download_vault(access_token=access_token, file_id=file_id).reference

    def create_vault(self, *, access_token: str, workspace_id: str) -> VaultReference:
        headers = self._headers(access_token=access_token)

        boundary = "dragon_vault_boundary"
        metadata = {"name": VAULT_FILENAME, "parents": ["appDataFolder"]}
        contents = {
            "schema_version": "1",
            "workspace_id": workspace_id,
            "events": [],
            "snapshot": None,
        }
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(metadata)}\r\n--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(contents, separators=(',', ':'))}\r\n--{boundary}--\r\n"
        ).encode()
        created = self.http.post(
            GOOGLE_DRIVE_UPLOAD_URL,
            headers={
                **headers,
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
            params={"uploadType": "multipart", "fields": "id"},
            data=body,
            timeout=20,
        )
        created_payload = created.json() if getattr(created, "ok", False) else None
        vault_id = str(created_payload.get("id") or "") if isinstance(created_payload, dict) else ""
        if not vault_id:
            raise GoogleOAuthError("Dragon could not create your private Google Drive workspace.")
        return VaultReference(file_id=vault_id, workspace_id=workspace_id)

    def ensure_vault(self, *, access_token: str, workspace_id: str) -> VaultReference:
        existing = self.locate_vault(access_token=access_token)
        return existing or self.create_vault(access_token=access_token, workspace_id=workspace_id)

    def read_vault(self, *, access_token: str, file_id: str) -> VaultDocument:
        return self._download_vault(access_token=access_token, file_id=file_id)

    def replace_vault(
        self,
        *,
        access_token: str,
        document: VaultDocument,
        payload: Mapping[str, Any],
    ) -> VaultDocument:
        next_payload = dict(payload)
        if str(next_payload.get("workspace_id") or "") != document.reference.workspace_id:
            raise ValueError("A vault update cannot change its workspace identity.")
        response = self.http.patch(
            f"{GOOGLE_DRIVE_UPLOAD_URL}/{quote(document.reference.file_id, safe='')}",
            headers={
                **self._headers(access_token=access_token, etag=document.etag),
                "Content-Type": "application/json; charset=UTF-8",
            },
            params={"uploadType": "media", "fields": "id,version"},
            data=json.dumps(
                next_payload, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8"),
            timeout=20,
        )
        if getattr(response, "status_code", None) == 412:
            raise GoogleVaultConflictError(
                "Your Google Drive workspace changed elsewhere. Reload it before saving."
            )
        if not getattr(response, "ok", False):
            raise GoogleOAuthError("Dragon could not save your private Google Drive workspace.")
        response_headers = getattr(response, "headers", {})
        etag = str(response_headers.get("ETag") or response_headers.get("etag") or "")
        return VaultDocument(
            reference=document.reference,
            payload=next_payload,
            etag=etag,
        )
