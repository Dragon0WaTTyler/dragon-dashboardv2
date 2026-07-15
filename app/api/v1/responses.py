from __future__ import annotations

from typing import Any

from flask import g, jsonify

from app.api.v1.schemas import API_VERSION


def item_response(item: dict[str, Any], status: int = 200):
    return jsonify({"ok": True, "api_version": API_VERSION, "item": item}), status


def collection_response(
    items: list[dict[str, Any]],
    *,
    total: int,
    limit: int,
    offset: int,
    status: int = 200,
    meta: dict[str, Any] | None = None,
):
    count = len(items)
    has_more = offset + count < total
    payload: dict[str, Any] = {
        "ok": True,
        "api_version": API_VERSION,
        "items": items,
        "count": count,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "next_offset": offset + count if has_more else None,
    }
    if meta:
        payload["meta"] = meta
    return (
        jsonify(payload),
        status,
    )


def error_response(
    code: str,
    message: str,
    status: int,
    *,
    fields: dict[str, str] | None = None,
):
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": g.request_id,
    }
    if fields:
        error["fields"] = fields
    return jsonify({"ok": False, "api_version": API_VERSION, "error": error}), status
