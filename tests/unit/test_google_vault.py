from __future__ import annotations

from typing import Any

import pytest

from app.vault.google import (
    GOOGLE_DRIVE_FILES_URL,
    WORKSPACE_CACHE_FILENAME,
    GoogleOAuthClient,
    GoogleVaultConflictError,
)


class FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        ok: bool = True,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        content: bytes = b"",
    ):
        self._payload = payload
        self.ok = ok
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeDriveHttp:
    def __init__(self, *, write_status: int = 200):
        self.write_status = write_status
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("get", url, kwargs))
        if url == GOOGLE_DRIVE_FILES_URL:
            return FakeResponse({"files": [{"id": "vault-file"}]})
        return FakeResponse(
            {
                "schema_version": "1",
                "workspace_id": "workspace_shared_42",
                "events": [],
                "snapshot": None,
            },
            headers={"ETag": "remote-etag"},
        )

    def patch(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("patch", url, kwargs))
        return FakeResponse(
            {"id": "vault-file"},
            ok=self.write_status < 400,
            status_code=self.write_status,
            headers={"ETag": "next-etag"},
        )


def _client(http: FakeDriveHttp) -> GoogleOAuthClient:
    return GoogleOAuthClient(
        {
            "DRAGON_GOOGLE_OAUTH_CLIENT_ID": "test-client",
            "DRAGON_GOOGLE_OAUTH_CLIENT_SECRET": "test-secret",
        },
        http=http,
    )


def test_google_vault_reads_an_existing_workspace_and_uses_etag_on_save():
    http = FakeDriveHttp()
    client = _client(http)

    reference = client.locate_vault(access_token="access-token")
    assert reference is not None
    assert reference.workspace_id == "workspace_shared_42"

    document = client.read_vault(access_token="access-token", file_id=reference.file_id)
    updated = client.replace_vault(
        access_token="access-token",
        document=document,
        payload={
            "schema_version": "1",
            "workspace_id": reference.workspace_id,
            "events": [{"id": "event-1"}],
            "snapshot": None,
        },
    )

    assert updated.etag == "next-etag"
    patch = next(call for call in http.calls if call[0] == "patch")
    assert patch[2]["headers"]["If-Match"] == "remote-etag"
    assert b'"event-1"' in patch[2]["data"]


def test_google_vault_rejects_a_stale_write_without_overwriting_remote_data():
    http = FakeDriveHttp(write_status=412)
    client = _client(http)
    document = client.read_vault(access_token="access-token", file_id="vault-file")

    with pytest.raises(GoogleVaultConflictError, match="changed elsewhere"):
        client.replace_vault(
            access_token="access-token",
            document=document,
            payload={
                "schema_version": "1",
                "workspace_id": "workspace_shared_42",
                "events": [],
                "snapshot": None,
            },
        )


class FakeWorkspaceCacheHttp:
    def __init__(self):
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("get", url, kwargs))
        if url == GOOGLE_DRIVE_FILES_URL:
            return FakeResponse(
                {
                    "files": [
                        {
                            "id": "cache-file",
                            "name": WORKSPACE_CACHE_FILENAME,
                            "version": "9",
                        }
                    ]
                }
            )
        return FakeResponse({}, headers={"ETag": "cache-etag"}, content=b"SQLite format 3\x00")

    def patch(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("patch", url, kwargs))
        return FakeResponse({}, headers={"Location": "https://upload.example.test/session"})

    def put(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("put", url, kwargs))
        return FakeResponse(
            {"id": "cache-file", "name": WORKSPACE_CACHE_FILENAME, "version": "10"},
            headers={"ETag": "next-cache-etag"},
        )


def test_google_workspace_cache_uses_resumable_upload_and_conditional_update():
    http = FakeWorkspaceCacheHttp()
    client = _client(http)

    current = client.find_appdata_file(
        access_token="access-token",
        name=WORKSPACE_CACHE_FILENAME,
    )
    assert current is not None
    contents, current = client.download_appdata_file(access_token="access-token", file=current)
    updated = client.upload_appdata_file(
        access_token="access-token",
        name=WORKSPACE_CACHE_FILENAME,
        contents=contents,
        current=current,
    )

    assert updated.version == "10"
    patch = next(call for call in http.calls if call[0] == "patch")
    assert patch[2]["headers"]["If-Match"] == "cache-etag"
    put = next(call for call in http.calls if call[0] == "put")
    assert put[2]["headers"]["Content-Range"] == f"bytes 0-{len(contents) - 1}/{len(contents)}"
