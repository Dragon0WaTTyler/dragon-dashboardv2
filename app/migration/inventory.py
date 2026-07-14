from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.shared.snapshots import SnapshotStore
from app.shared.time import utc_iso

IGNORED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}
SENSITIVE_MARKERS = (".env", "token", "secret", "credential", "oauth")
STRUCTURED_SUFFIXES = {".csv", ".db", ".json", ".jsonl", ".sqlite", ".sqlite3", ".xml"}


@dataclass(frozen=True, slots=True)
class InventoryResult:
    manifest: dict[str, Any]
    warnings: list[str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sensitive(path: Path) -> bool:
    name = path.name.lower()
    return any(marker in name for marker in SENSITIVE_MARKERS)


def _json_shape(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(value, list):
        shape: dict[str, Any] = {"type": "list", "count": len(value)}
        if value and isinstance(value[0], dict):
            shape["item_keys"] = sorted(str(key) for key in value[0])[:80]
        return shape
    if isinstance(value, dict):
        shape = {"type": "object", "key_count": len(value)}
        if len(value) <= 50:
            shape["keys"] = sorted(str(key) for key in value)[:80]
        collections: dict[str, int] = {}
        item_keys: dict[str, list[str]] = {}
        for key, item in value.items():
            if isinstance(item, (list, dict)):
                collections[str(key)] = len(item)
            if isinstance(item, list) and item and isinstance(item[0], dict):
                item_keys[str(key)] = sorted(str(field) for field in item[0])[:80]
        if collections and len(collections) <= 50:
            shape["collection_counts"] = collections
        if item_keys:
            shape["item_keys"] = item_keys
        return shape
    return {"type": type(value).__name__}


def _csv_shape(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        columns = next(reader, [])
        row_count = sum(1 for _ in reader)
    return {"type": "csv", "row_count": row_count, "columns": columns[:100]}


def _sqlite_shape(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        tables: dict[str, Any] = {}
        names = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        for (name,) in names:
            quoted = str(name).replace('"', '""')
            columns = [
                {"name": row[1], "type": row[2]}
                for row in connection.execute(f'PRAGMA table_info("{quoted}")')
            ]
            row_count = connection.execute(
                f'SELECT COUNT(*) FROM "{quoted}"'  # noqa: S608 - quoted sqlite identifier
            ).fetchone()[0]
            tables[str(name)] = {"columns": columns, "row_count": row_count}
        return {"type": "sqlite", "tables": tables}
    finally:
        connection.close()


def _jsonl_shape(path: Path) -> dict[str, Any]:
    row_count = 0
    item_keys: list[str] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            row_count += 1
            if row_count == 1:
                value = json.loads(line)
                if isinstance(value, dict):
                    item_keys = sorted(str(key) for key in value)[:80]
    return {"type": "jsonl", "row_count": row_count, "item_keys": item_keys}


def _schema(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _json_shape(path)
    if suffix == ".csv":
        return _csv_shape(path)
    if suffix in {".db", ".sqlite", ".sqlite3"}:
        return _sqlite_shape(path)
    if suffix == ".jsonl":
        return _jsonl_shape(path)
    return {"type": suffix.removeprefix(".") or "unknown"}


def build_inventory(source: str | Path) -> InventoryResult:
    root = Path(source).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Migration source must be a directory.")

    entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    classifications: Counter[str] = Counter()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink() or any(part in IGNORED_DIRECTORIES for part in relative.parts):
            continue
        if not path.is_file() or path.name.startswith("._"):
            continue
        suffix = path.suffix.lower()
        sensitive = _is_sensitive(path)
        structured = suffix in STRUCTURED_SUFFIXES
        classification = (
            "excluded_sensitive" if sensitive else "structured_data" if structured else "ignored"
        )
        classifications[classification] += 1
        entry: dict[str, Any] = {
            "path": relative.as_posix(),
            "bytes": path.stat().st_size,
            "modified_ns": path.stat().st_mtime_ns,
            "classification": classification,
        }
        if not sensitive:
            entry["sha256"] = _sha256(path)
        if structured and not sensitive:
            try:
                entry["schema"] = _schema(path)
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
                entry["schema"] = {"type": "unreadable_or_malformed"}
                warnings.append(f"Could not inspect {relative.as_posix()}: {type(exc).__name__}")
        entries.append(entry)

    manifest = {
        "schema_version": "dragon-legacy-inventory.v1",
        "generated_at": utc_iso(),
        "source_name": root.name,
        "source_root_checksum": hashlib.sha256(str(root).encode()).hexdigest(),
        "counts": {**dict(classifications), "total": len(entries)},
        "entries": entries,
    }
    return InventoryResult(manifest=manifest, warnings=warnings)


def write_inventory(result: InventoryResult, output_root: str | Path) -> dict[str, str]:
    root = Path(output_root).resolve()
    store = SnapshotStore(root)
    write_result = store.write(
        "legacy-inventory",
        result.manifest,
        schema_version="dragon-legacy-inventory.v1",
    )
    markdown_path = root / "legacy-inventory.md"
    counts = result.manifest["counts"]
    lines = [
        "# Legacy migration inventory",
        "",
        f"Generated: {result.manifest['generated_at']}",
        f"Source label: `{result.manifest['source_name']}`",
        "",
        "## Counts",
        "",
        f"- Structured data: {counts.get('structured_data', 0)}",
        f"- Sensitive files excluded: {counts.get('excluded_sensitive', 0)}",
        f"- Ignored files: {counts.get('ignored', 0)}",
        f"- Total inventoried: {counts.get('total', 0)}",
        "",
        "No record values or credential contents are included in this report.",
    ]
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {**write_result, "markdown_path": markdown_path.name}
