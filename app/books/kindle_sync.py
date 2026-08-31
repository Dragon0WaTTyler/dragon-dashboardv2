from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests

from app.books.clippings import (
    KindleClippingsOutboxItem,
    KindleClippingsSyncState,
    mark_clippings_failed,
    mark_clippings_uploaded,
)
from app.shared.time import utc_iso
from app.vault.integrations import integration_settings, update_integration_settings

NOTION_API_BASE_URL = "https://api.notion.com/v1"
KINDLE_NOTION_VERSION = "2025-09-03"
KINDLE_NOTION_TIMEOUT_SECONDS = 15


@dataclass(frozen=True, slots=True)
class KindleSyncCredentialStatus:
    token_file_present: bool
    token_configured: bool
    metadata_present: bool
    metadata_valid: bool
    target_kind: str = ""
    target_id_configured: bool = False
    destination_label: str = "Book Quotes"
    validated_at: str = ""
    last_checked_at: str = ""
    last_validation_error: str = ""
    note: str = ""

    @property
    def clearable(self) -> bool:
        return self.token_file_present or self.metadata_present

    @property
    def validation_state(self) -> str:
        if self.validated_at:
            return "valid"
        if self.last_validation_error:
            return "invalid"
        return "not_checked"

    @property
    def state(self) -> str:
        if (
            self.token_configured
            and self.metadata_valid
            and self.target_id_configured
            and not self.last_validation_error
        ):
            return "validated" if self.validated_at else "configured"
        if self.clearable:
            return "needs_review"
        return "missing"


@dataclass(frozen=True, slots=True)
class KindleSyncCredentialClearResult:
    status: KindleSyncCredentialStatus
    cleared: int


@dataclass(frozen=True, slots=True)
class KindleSyncCredentialValidateResult:
    status: KindleSyncCredentialStatus
    validated: bool


@dataclass(frozen=True, slots=True)
class KindleBookQuotesSyncResult:
    state: KindleClippingsSyncState
    uploaded: int
    skipped_existing: int
    failed: int


class KindleSyncCredentialStore:
    def __init__(self, *, token_path: Path | str, metadata_path: Path | str):
        self.token_path = Path(token_path)
        self.metadata_path = Path(metadata_path)

    def status(self) -> KindleSyncCredentialStatus:
        note = ""
        token_file_present = self.token_path.exists()
        token_configured = False
        if token_file_present:
            try:
                token_configured = bool(self.token_path.read_text(encoding="utf-8").strip())
            except OSError:
                note = "Local Kindle sync secret could not be read."

        payload: Mapping | None = None
        metadata_present = self.metadata_path.exists()
        metadata_valid = False
        target_kind = ""
        target_id_configured = False
        destination_label = "Book Quotes"
        validated_at = ""
        last_checked_at = ""
        last_validation_error = ""
        if metadata_present:
            try:
                candidate_payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                note = note or "Local Kindle sync metadata could not be read."
            else:
                if isinstance(candidate_payload, Mapping):
                    payload = candidate_payload
                    metadata_valid = True
                    target_kind = _target_kind(payload)
                    target_id_configured = bool(_target_id(payload))
                    destination_label = _destination_label(payload)
                    validated_at = str(payload.get("validated_at") or "").strip()
                    last_checked_at = str(payload.get("last_checked_at") or "").strip()
                    last_validation_error = str(
                        payload.get("last_validation_error") or ""
                    ).strip()
                else:
                    note = note or "Local Kindle sync metadata is incomplete."
        if metadata_present and metadata_valid and not target_id_configured and not note:
            note = "Local Book Quotes target ID is missing."
        if last_validation_error and not note:
            note = last_validation_error

        return KindleSyncCredentialStatus(
            token_file_present=token_file_present,
            token_configured=token_configured,
            metadata_present=metadata_present,
            metadata_valid=metadata_valid,
            target_kind=target_kind,
            target_id_configured=target_id_configured,
            destination_label=destination_label,
            validated_at=validated_at,
            last_checked_at=last_checked_at,
            last_validation_error=last_validation_error,
            note=note,
        )

    def clear(self) -> KindleSyncCredentialClearResult:
        cleared = 0
        for path in (self.token_path, self.metadata_path):
            try:
                if path.exists():
                    path.unlink()
                    cleared += 1
            except OSError:
                continue
        return KindleSyncCredentialClearResult(status=self.status(), cleared=cleared)

    def validate(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = KINDLE_NOTION_TIMEOUT_SECONDS,
    ) -> KindleSyncCredentialValidateResult:
        status = self.status()
        checked_at = utc_iso()
        payload = self._load_metadata_payload()
        if not status.token_configured:
            return KindleSyncCredentialValidateResult(status=status, validated=False)
        if payload is None:
            return KindleSyncCredentialValidateResult(status=status, validated=False)
        target_kind = _target_kind(payload)
        target_id = _target_id(payload)
        if not target_kind or not target_id:
            payload["validated_at"] = ""
            payload["last_checked_at"] = checked_at
            payload["last_validation_error"] = "Local Book Quotes target ID is missing."
            self._save_metadata_payload(payload)
            return KindleSyncCredentialValidateResult(
                status=self.status(),
                validated=False,
            )

        token = self.token_path.read_text(encoding="utf-8").strip()
        client = KindleSyncValidationClient(
            token=token,
            session=session,
            timeout_seconds=timeout_seconds,
        )
        try:
            details = client.validate_target(target_kind=target_kind, target_id=target_id)
        except KindleSyncValidationError as exc:
            payload["validated_at"] = ""
            payload["last_checked_at"] = checked_at
            payload["last_validation_error"] = str(exc)
            self._save_metadata_payload(payload)
            return KindleSyncCredentialValidateResult(
                status=self.status(),
                validated=False,
            )

        destination = dict(payload.get("destination") or {})
        destination["label"] = str(destination.get("label") or details["label"]).strip()
        destination["kind"] = details["target_kind"]
        if details.get("database_id"):
            destination["database_id"] = details["database_id"]
        if details.get("data_source_id"):
            destination["data_source_id"] = details["data_source_id"]
        payload["destination"] = destination
        payload["validated_at"] = checked_at
        payload["last_checked_at"] = checked_at
        payload["last_validation_error"] = ""
        self._save_metadata_payload(payload)
        return KindleSyncCredentialValidateResult(status=self.status(), validated=True)

    def _load_metadata_payload(self) -> dict | None:
        try:
            payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, Mapping):
            return None
        return dict(payload)

    def _save_metadata_payload(self, payload: Mapping) -> None:
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self.metadata_path.write_text(
            json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def sync_pending(
        self,
        state: KindleClippingsSyncState | Mapping,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = KINDLE_NOTION_TIMEOUT_SECONDS,
    ) -> KindleBookQuotesSyncResult:
        current = (
            state
            if isinstance(state, KindleClippingsSyncState)
            else KindleClippingsSyncState.from_dict(state)
        )
        status = self.status()
        payload = self._load_metadata_payload()
        if not status.token_configured:
            failed = mark_clippings_failed(
                current,
                {
                    item.unique_hash: "Local Kindle sync token is missing."
                    for item in current.pending
                },
            )
            return KindleBookQuotesSyncResult(
                state=failed.state,
                uploaded=0,
                skipped_existing=0,
                failed=failed.failed,
            )
        if payload is None:
            failed = mark_clippings_failed(
                current,
                {
                    item.unique_hash: "Local Kindle sync metadata is missing."
                    for item in current.pending
                },
            )
            return KindleBookQuotesSyncResult(
                state=failed.state,
                uploaded=0,
                skipped_existing=0,
                failed=failed.failed,
            )
        target_kind = _target_kind(payload)
        target_id = _target_id(payload)
        if not target_kind or not target_id:
            failed = mark_clippings_failed(
                current,
                {
                    item.unique_hash: "Local Book Quotes target ID is missing."
                    for item in current.pending
                },
            )
            return KindleBookQuotesSyncResult(
                state=failed.state,
                uploaded=0,
                skipped_existing=0,
                failed=failed.failed,
            )

        token = self.token_path.read_text(encoding="utf-8").strip()
        client = KindleBookQuotesClient(
            token=token,
            target_kind=target_kind,
            target_id=target_id,
            session=session,
            timeout_seconds=timeout_seconds,
        )
        uploaded_hashes: list[str] = []
        skipped_existing = 0
        failures: dict[str, str] = {}
        imported_at = utc_iso()

        for item in current.pending:
            try:
                if client.has_existing_hash(item.unique_hash):
                    uploaded_hashes.append(item.unique_hash)
                    skipped_existing += 1
                    continue
                client.create_quote_page(item, imported_at=imported_at)
            except KindleSyncValidationError as exc:
                failures[item.unique_hash] = str(exc)
                continue
            uploaded_hashes.append(item.unique_hash)

        uploaded = mark_clippings_uploaded(current, uploaded_hashes)
        failed = mark_clippings_failed(uploaded.state, failures)
        return KindleBookQuotesSyncResult(
            state=failed.state,
            uploaded=uploaded.uploaded - skipped_existing,
            skipped_existing=skipped_existing,
            failed=failed.failed,
        )

    def book_quotes_client(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = KINDLE_NOTION_TIMEOUT_SECONDS,
    ) -> KindleBookQuotesClient:
        status = self.status()
        payload = self._load_metadata_payload()
        if not status.token_configured:
            raise KindleSyncValidationError("Local Kindle sync token is missing.")
        if payload is None:
            raise KindleSyncValidationError("Local Kindle sync metadata is missing.")
        target_kind = _target_kind(payload)
        target_id = _target_id(payload)
        if not target_kind or not target_id:
            raise KindleSyncValidationError("Local Book Quotes target ID is missing.")
        token = self.token_path.read_text(encoding="utf-8").strip()
        return KindleBookQuotesClient(
            token=token,
            target_kind=target_kind,
            target_id=target_id,
            session=session,
            timeout_seconds=timeout_seconds,
        )


class WorkspaceKindleSyncCredentialStore:
    """Use only the active personal workspace's Notion connection.

    The legacy file-backed store is intentionally retained for a local-only
    installation.  A signed-in personal workspace must never fall back to
    those shared instance files.
    """

    _VALIDATION_PROVIDER = "kindle_sync"

    def _connection(self) -> tuple[str, str, str]:
        settings = integration_settings("notion")
        token = str(settings.get("token") or "").strip()
        data_source_id = str(settings.get("book_quotes_data_source_id") or "").strip()
        database_id = str(settings.get("book_quotes_database_id") or "").strip()
        return token, data_source_id, database_id

    def status(self) -> KindleSyncCredentialStatus:
        token, data_source_id, database_id = self._connection()
        validation = integration_settings(self._VALIDATION_PROVIDER)
        target_id = data_source_id or database_id
        target_kind = "data_source" if data_source_id else "database"
        configured = bool(token and target_id)
        return KindleSyncCredentialStatus(
            token_file_present=bool(token),
            token_configured=bool(token),
            metadata_present=bool(target_id),
            metadata_valid=bool(target_id),
            target_kind=target_kind if target_id else "",
            target_id_configured=bool(target_id),
            destination_label="Personal Book Quotes",
            validated_at=str(validation.get("validated_at") or ""),
            last_checked_at=str(validation.get("last_checked_at") or ""),
            last_validation_error=str(validation.get("last_validation_error") or ""),
            note=(
                "Connect Notion and set a Book Quotes database in Personal workspace."
                if not configured
                else ""
            ),
        )

    def clear(self) -> KindleSyncCredentialClearResult:
        settings = integration_settings("notion")
        cleared = 0
        for key in ("book_quotes_data_source_id", "book_quotes_database_id"):
            if settings.pop(key, ""):
                cleared += 1
        update_integration_settings("notion", settings)
        update_integration_settings(self._VALIDATION_PROVIDER, {})
        return KindleSyncCredentialClearResult(status=self.status(), cleared=cleared)

    def validate(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = KINDLE_NOTION_TIMEOUT_SECONDS,
    ) -> KindleSyncCredentialValidateResult:
        token, data_source_id, database_id = self._connection()
        checked_at = utc_iso()
        target_id = data_source_id or database_id
        target_kind = "data_source" if data_source_id else "database"
        if not token or not target_id:
            return KindleSyncCredentialValidateResult(status=self.status(), validated=False)
        try:
            KindleSyncValidationClient(
                token=token, session=session, timeout_seconds=timeout_seconds
            ).validate_target(target_kind=target_kind, target_id=target_id)
        except KindleSyncValidationError as exc:
            update_integration_settings(
                self._VALIDATION_PROVIDER,
                {"last_checked_at": checked_at, "last_validation_error": str(exc)},
            )
            return KindleSyncCredentialValidateResult(status=self.status(), validated=False)
        update_integration_settings(
            self._VALIDATION_PROVIDER,
            {
                "validated_at": checked_at,
                "last_checked_at": checked_at,
                "last_validation_error": "",
            },
        )
        return KindleSyncCredentialValidateResult(status=self.status(), validated=True)

    def sync_pending(
        self,
        state: KindleClippingsSyncState | Mapping,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = KINDLE_NOTION_TIMEOUT_SECONDS,
    ) -> KindleBookQuotesSyncResult:
        current = (
            state
            if isinstance(state, KindleClippingsSyncState)
            else KindleClippingsSyncState.from_dict(state)
        )
        token, data_source_id, database_id = self._connection()
        target_id = data_source_id or database_id
        if not token or not target_id:
            failed = mark_clippings_failed(
                current,
                {
                    item.unique_hash: "Personal Book Quotes is not configured."
                    for item in current.pending
                },
            )
            return KindleBookQuotesSyncResult(
                state=failed.state,
                uploaded=0,
                skipped_existing=0,
                failed=failed.failed,
            )
        client = KindleBookQuotesClient(
            token=token,
            target_kind="data_source" if data_source_id else "database",
            target_id=target_id,
            session=session,
            timeout_seconds=timeout_seconds,
        )
        uploaded_hashes: list[str] = []
        skipped_existing = 0
        failures: dict[str, str] = {}
        imported_at = utc_iso()
        for item in current.pending:
            try:
                if client.has_existing_hash(item.unique_hash):
                    uploaded_hashes.append(item.unique_hash)
                    skipped_existing += 1
                    continue
                client.create_quote_page(item, imported_at=imported_at)
            except KindleSyncValidationError as exc:
                failures[item.unique_hash] = str(exc)
                continue
            uploaded_hashes.append(item.unique_hash)
        uploaded = mark_clippings_uploaded(current, uploaded_hashes)
        failed = mark_clippings_failed(uploaded.state, failures)
        return KindleBookQuotesSyncResult(
            state=failed.state,
            uploaded=uploaded.uploaded - skipped_existing,
            skipped_existing=skipped_existing,
            failed=failed.failed,
        )


class KindleSyncValidationError(RuntimeError):
    pass


class KindleSyncValidationClient:
    def __init__(
        self,
        *,
        token: str,
        session: requests.Session | None = None,
        timeout_seconds: float = KINDLE_NOTION_TIMEOUT_SECONDS,
    ) -> None:
        self.token = token.strip()
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def validate_target(self, *, target_kind: str, target_id: str) -> dict[str, str]:
        normalized_kind = str(target_kind or "").strip().casefold()
        normalized_id = _clean_id(target_id)
        if normalized_kind not in {"data_source", "database"} or not normalized_id:
            raise KindleSyncValidationError("Local Book Quotes target is incomplete.")
        path_root = "data_sources" if normalized_kind == "data_source" else "databases"
        payload = self._request_json("GET", f"/{path_root}/{normalized_id}")
        if normalized_kind == "data_source":
            return {
                "target_kind": "data_source",
                "data_source_id": str(payload.get("id") or normalized_id),
                "database_id": _clean_id(
                    ((payload.get("parent") or {}).get("database_id"))
                    or ((payload.get("database_parent") or {}).get("database_id"))
                    or ""
                ),
                "label": _notion_title(payload, fallback="Book Quotes"),
            }
        sources = payload.get("data_sources") or []
        if not sources:
            raise KindleSyncValidationError(
                "The configured Book Quotes database has no accessible data source."
            )
        source_id = _clean_id(str((sources[0] or {}).get("id") or ""))
        if not source_id:
            raise KindleSyncValidationError(
                "The configured Book Quotes database did not return a usable data source ID."
            )
        return {
            "target_kind": "database",
            "database_id": str(payload.get("id") or normalized_id),
            "data_source_id": source_id,
            "label": _notion_title(payload, fallback="Book Quotes"),
        }

    def _request_json(self, method: str, path: str, **kwargs) -> dict:
        if not self.token:
            raise KindleSyncValidationError("Local Kindle sync token is empty.")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": KINDLE_NOTION_VERSION,
            "Accept": "application/json",
        }
        headers.update(dict(kwargs.pop("headers", {}) or {}))
        try:
            response = self.session.request(
                method,
                f"{NOTION_API_BASE_URL}{path}",
                timeout=self.timeout_seconds,
                headers=headers,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise KindleSyncValidationError(
                "Notion validation request failed."
            ) from exc
        if response.status_code >= 400:
            try:
                message = str((response.json() or {}).get("message") or "").strip()
            except ValueError:
                message = ""
            raise KindleSyncValidationError(
                message or f"Notion returned HTTP {response.status_code}."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise KindleSyncValidationError("Notion returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise KindleSyncValidationError("Notion returned an unexpected payload.")
        return payload


class KindleBookQuotesClient(KindleSyncValidationClient):
    FIELD_ALIASES = {
        "quote": {"quote", "highlight", "text", "clipping"},
        "book_title": {"booktitle", "bookname"},
        "book_relation_ids": {"book", "books", "bookrelation", "bookrelations"},
        "author": {"author", "bookauthor"},
        "location": {"location", "kindlelocation"},
        "page": {"page"},
        "created_at": {"createdat", "clippingdate", "clippedat"},
        "imported_at": {"importedat", "importdate", "syncedat"},
        "source": {"source"},
        "unique_hash": {"uniquehash", "hash", "clippinghash"},
        "dragon_book_id": {"dragonbookid"},
        "sync_status": {"syncstatus"},
        "sync_device": {"syncdevice", "device"},
        "kind": {"kind", "clippingkind"},
    }

    def __init__(
        self,
        *,
        token: str,
        target_kind: str,
        target_id: str,
        session: requests.Session | None = None,
        timeout_seconds: float = KINDLE_NOTION_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(
            token=token,
            session=session,
            timeout_seconds=timeout_seconds,
        )
        self.target_kind = str(target_kind or "").strip().casefold()
        self.target_id = _clean_id(target_id)
        self._data_source_id: str | None = None
        self._schema: dict | None = None
        self._title_property_name: str | None = None
        self._field_map: dict[str, tuple[str, Mapping]] | None = None

    @property
    def data_source_id(self) -> str:
        if self._data_source_id:
            return self._data_source_id
        details = self.validate_target(target_kind=self.target_kind, target_id=self.target_id)
        data_source_id = _clean_id(details.get("data_source_id") or "")
        if not data_source_id:
            raise KindleSyncValidationError(
                "The configured Book Quotes target did not return a data source ID."
            )
        self._data_source_id = data_source_id
        return self._data_source_id

    def schema(self) -> dict:
        if self._schema is None:
            payload = self._request_json("GET", f"/data_sources/{self.data_source_id}")
            properties = payload.get("properties") or {}
            if not isinstance(properties, dict):
                raise KindleSyncValidationError(
                    "The Book Quotes data source did not return a usable schema."
                )
            self._schema = properties
        return self._schema

    def has_existing_hash(self, unique_hash: str) -> bool:
        property_name, definition = self._unique_hash_property()
        filter_body = _notion_text_filter(
            property_name,
            prop_type=str(definition.get("type") or ""),
            value=unique_hash,
        )
        payload = self._request_json(
            "POST",
            f"/data_sources/{self.data_source_id}/query",
            body={"filter": filter_body, "page_size": 1},
        )
        return bool(payload.get("results"))

    def create_quote_page(
        self,
        item: KindleClippingsOutboxItem,
        *,
        imported_at: str,
    ) -> dict:
        properties = self._page_properties(item, imported_at=imported_at)
        payload = self._request_json(
            "POST",
            "/pages",
            body={
                "parent": {
                    "type": "data_source_id",
                    "data_source_id": self.data_source_id,
                },
                "properties": properties,
            },
        )
        return payload

    def list_quote_pages(self) -> list[dict]:
        pages: list[dict] = []
        cursor = ""
        while True:
            body = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            payload = self._request_json(
                "POST",
                f"/data_sources/{self.data_source_id}/query",
                body=body,
            )
            results = payload.get("results") or []
            if not isinstance(results, list):
                raise KindleSyncValidationError(
                    "The Book Quotes query returned an unexpected payload."
                )
            pages.extend(
                page for page in results if isinstance(page, dict) and not page.get("in_trash")
            )
            if not payload.get("has_more") or not payload.get("next_cursor"):
                break
            cursor = str(payload.get("next_cursor") or "").strip()
            if not cursor:
                break
        return pages

    def quote_payload_from_page(self, page: Mapping) -> dict[str, object]:
        properties = page.get("properties") or {}
        if not isinstance(properties, Mapping):
            raise KindleSyncValidationError(
                "The Book Quotes page payload did not include usable properties."
            )
        field_map = self._schema_field_map()
        quote_text = ""
        quote_info = field_map.get("quote")
        if quote_info is not None:
            quote_text = _decode_notion_property(properties.get(quote_info[0]))
        if not quote_text and self._title_property_name:
            quote_text = _decode_notion_property(properties.get(self._title_property_name))
        payload = {
            "quote": quote_text,
            "book_title": _decoded_field(properties, field_map, "book_title"),
            "book_relation_ids": _decoded_field(
                properties, field_map, "book_relation_ids"
            ),
            "author": _decoded_field(properties, field_map, "author"),
            "location": _decoded_field(properties, field_map, "location"),
            "page": _decoded_field(properties, field_map, "page"),
            "created_at": _decoded_field(properties, field_map, "created_at"),
            "imported_at": _decoded_field(properties, field_map, "imported_at"),
            "source": _decoded_field(properties, field_map, "source") or "Kindle",
            "unique_hash": _decoded_field(properties, field_map, "unique_hash")
            or _clean_id(str(page.get("id") or "")),
            "dragon_book_id": _decoded_field(properties, field_map, "dragon_book_id"),
            "sync_status": _decoded_field(properties, field_map, "sync_status"),
            "sync_device": _decoded_field(properties, field_map, "sync_device"),
            "kind": _decoded_field(properties, field_map, "kind") or "highlight",
        }
        return payload

    def _unique_hash_property(self) -> tuple[str, Mapping]:
        field_map = self._schema_field_map()
        property_info = field_map.get("unique_hash")
        if property_info is None:
            raise KindleSyncValidationError(
                "The Book Quotes data source needs a Unique Hash property before sync can run."
            )
        return property_info

    def _schema_field_map(self) -> dict[str, tuple[str, Mapping]]:
        if self._field_map is not None:
            return self._field_map
        result: dict[str, tuple[str, Mapping]] = {}
        title_name: str | None = None
        for name, definition in self.schema().items():
            if str(definition.get("type") or "") == "title":
                title_name = name
                break
        self._title_property_name = title_name
        for local_name, aliases in self.FIELD_ALIASES.items():
            for property_name, definition in self.schema().items():
                normalized = _normalize_property_name(property_name)
                if normalized in aliases:
                    result[local_name] = (property_name, definition)
                    break
        if "book_relation_ids" not in result:
            relation_fields = [
                (property_name, definition)
                for property_name, definition in self.schema().items()
                if str(definition.get("type") or "") == "relation"
            ]
            if len(relation_fields) == 1:
                result["book_relation_ids"] = relation_fields[0]
        self._field_map = result
        return result

    def _page_properties(
        self,
        item: KindleClippingsOutboxItem,
        *,
        imported_at: str,
    ) -> dict[str, dict]:
        field_map = self._schema_field_map()
        properties: dict[str, dict] = {}
        quote_text = str(item.payload.get("quote") or item.payload.get("kind") or "").strip()
        title_name = self._title_property_name
        if not title_name:
            raise KindleSyncValidationError(
                "The Book Quotes data source needs a title property before sync can run."
            )
        title_definition = self.schema().get(title_name) or {}
        title_payload = _encode_notion_property(
            title_definition,
            quote_text[:2000],
        )
        if title_payload is None:
            raise KindleSyncValidationError(
                "The Book Quotes title property could not accept the clipping text."
            )
        properties[title_name] = title_payload

        payload_values = {
            "quote": quote_text,
            "book_title": str(
                item.payload.get("matched_book_title")
                or item.payload.get("book_title")
                or ""
            ).strip(),
            "author": str(item.payload.get("author") or "").strip(),
            "location": str(item.payload.get("location") or "").strip(),
            "page": str(item.payload.get("page") or "").strip(),
            "created_at": _kindle_created_at_iso(str(item.payload.get("created_at") or "").strip()),
            "imported_at": imported_at,
            "source": "Kindle",
            "unique_hash": item.unique_hash,
            "dragon_book_id": str(item.payload.get("dragon_book_id") or "").strip(),
            "sync_status": "Synced",
            "sync_device": "Kindle",
            "kind": str(item.payload.get("kind") or "").strip().title(),
        }

        for field_name, (property_name, definition) in field_map.items():
            if property_name == title_name and field_name == "quote":
                continue
            value = payload_values.get(field_name)
            encoded = _encode_notion_property(definition, value)
            if encoded is not None:
                properties[property_name] = encoded
        return properties

    def _request_json(self, method: str, path: str, *, body: Mapping | None = None) -> dict:
        kwargs = {}
        if body is not None:
            kwargs["json"] = dict(body)
            kwargs["headers"] = {"Content-Type": "application/json"}
        return super()._request_json(method, path, **kwargs)


def _clean_id(value: str | None) -> str:
    return str(value or "").strip().replace("-", "")


def _destination_label(payload: Mapping) -> str:
    destination = payload.get("destination")
    if isinstance(destination, Mapping):
        label = str(destination.get("label") or "").strip()
        if label:
            return label
    label = str(payload.get("destination_label") or "").strip()
    return label or "Book Quotes"


def _target_kind(payload: Mapping) -> str:
    destination = payload.get("destination")
    if isinstance(destination, Mapping):
        value = str(destination.get("kind") or "").strip().casefold()
        if value in {"data_source", "database"}:
            return value
    if _clean_id(payload.get("data_source_id")) or _clean_id(
        (destination or {}).get("data_source_id") if isinstance(destination, Mapping) else ""
    ):
        return "data_source"
    if _clean_id(payload.get("database_id")) or _clean_id(
        (destination or {}).get("database_id") if isinstance(destination, Mapping) else ""
    ):
        return "database"
    return ""


def _target_id(payload: Mapping) -> str:
    destination = payload.get("destination")
    if isinstance(destination, Mapping):
        if _clean_id(destination.get("data_source_id")):
            return _clean_id(destination.get("data_source_id"))
        if _clean_id(destination.get("database_id")):
            return _clean_id(destination.get("database_id"))
    if _clean_id(payload.get("data_source_id")):
        return _clean_id(payload.get("data_source_id"))
    return _clean_id(payload.get("database_id"))


def _notion_title(payload: Mapping, *, fallback: str) -> str:
    title = payload.get("title")
    if isinstance(title, list):
        text = "".join(
            str(part.get("plain_text") or "")
            for part in title
            if isinstance(part, Mapping)
        ).strip()
        if text:
            return text
    return fallback


def _normalize_property_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _notion_text_filter(property_name: str, *, prop_type: str, value: str) -> dict:
    normalized_type = str(prop_type or "").strip()
    if normalized_type not in {"title", "rich_text"}:
        raise KindleSyncValidationError(
            "The Book Quotes Unique Hash property must be a title or rich text field."
        )
    return {
        "property": property_name,
        normalized_type: {"equals": str(value or "")},
    }


def _encode_notion_property(definition: Mapping, value: object) -> dict | None:
    prop_type = str(definition.get("type") or "").strip()
    if value in {None, ""}:
        if prop_type in {"title", "rich_text"}:
            return None
        if prop_type == "date":
            return None
        if prop_type == "relation":
            return None
        if prop_type == "multi_select":
            return None
        if prop_type in {"select", "status"}:
            return None
    if prop_type in {"title", "rich_text"}:
        content = str(value or "")[:2000]
        if not content:
            return None
        return {
            prop_type: [
                {
                    "type": "text",
                    "text": {"content": content},
                }
            ]
        }
    if prop_type == "number":
        number = _coerce_number(value)
        return {"number": number} if number is not None else None
    if prop_type == "checkbox":
        return {"checkbox": bool(value)}
    if prop_type in {"select", "status"}:
        option = _schema_option_name(definition, str(value or ""))
        return {prop_type: {"name": option}} if option else None
    if prop_type == "multi_select":
        option = _schema_option_name(definition, str(value or ""))
        return {"multi_select": [{"name": option}]} if option else None
    if prop_type == "date":
        date_value = str(value or "").strip()
        return {"date": {"start": date_value}} if date_value else None
    return None


def _schema_option_name(definition: Mapping, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    config = definition.get(str(definition.get("type") or "")) or {}
    options = config.get("options") or []
    for option in options:
        name = str((option or {}).get("name") or "").strip()
        if name.casefold() == text.casefold():
            return name
    return ""


def _coerce_number(value: object) -> int | float | None:
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return None


def _kindle_created_at_iso(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for pattern in ("%A, %B %d, %Y %I:%M:%S %p", "%B %d, %Y %I:%M:%S %p"):
        try:
            return utc_iso(datetime.strptime(text, pattern))
        except ValueError:
            continue
    return ""


def _decode_notion_property(prop: object) -> str:
    if not isinstance(prop, Mapping):
        return ""
    prop_type = str(prop.get("type") or "").strip()
    value = prop.get(prop_type)
    if prop_type in {"title", "rich_text"} and isinstance(value, list):
        return "".join(
            str(part.get("plain_text") or "")
            for part in value
            if isinstance(part, Mapping)
        ).strip()
    if prop_type == "number":
        return "" if value in {None, ""} else str(value)
    if prop_type == "checkbox":
        return "true" if bool(value) else ""
    if prop_type in {"select", "status"} and isinstance(value, Mapping):
        return str(value.get("name") or "").strip()
    if prop_type == "date" and isinstance(value, Mapping):
        return str(value.get("start") or "").strip()
    if prop_type == "multi_select" and isinstance(value, list):
        return ", ".join(
            str(option.get("name") or "").strip()
            for option in value
            if isinstance(option, Mapping) and str(option.get("name") or "").strip()
        )
    if prop_type == "relation" and isinstance(value, list):
        return ", ".join(
            _clean_id(str(item.get("id") or ""))
            for item in value
            if isinstance(item, Mapping) and _clean_id(str(item.get("id") or ""))
        )
    if prop_type in {"url", "email", "phone_number"}:
        return str(value or "").strip()
    if prop_type == "formula" and isinstance(value, Mapping):
        return str(value.get(str(value.get("type") or "")) or "").strip()
    return ""


def _decoded_field(
    properties: Mapping,
    field_map: Mapping[str, tuple[str, Mapping]],
    field_name: str,
) -> str:
    property_info = field_map.get(field_name)
    if property_info is None:
        return ""
    property_name, _definition = property_info
    return _decode_notion_property(properties.get(property_name))
