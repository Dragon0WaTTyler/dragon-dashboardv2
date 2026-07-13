from __future__ import annotations

from typing import Any, NotRequired, TypedDict

API_VERSION = "v1"


class ApiError(TypedDict):
    code: str
    message: str
    fields: NotRequired[dict[str, str]]
    request_id: str


class ErrorEnvelope(TypedDict):
    ok: bool
    api_version: str
    error: ApiError


class ItemEnvelope(TypedDict):
    ok: bool
    api_version: str
    item: dict[str, Any]


class CollectionEnvelope(TypedDict):
    ok: bool
    api_version: str
    items: list[dict[str, Any]]
    count: int
    total: int
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None
