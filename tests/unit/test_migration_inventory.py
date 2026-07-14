import json

from app.migration.inventory import build_inventory, write_inventory


def test_inventory_reports_schemas_without_reading_secret_values(tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "movies.json").write_text(
        json.dumps([{"id": "m1", "title": "Private title", "status": "watching"}]),
        encoding="utf-8",
    )
    (source / ".env").write_bytes(b"TOKEN=private-value\xff")
    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in source.iterdir()}

    result = build_inventory(source)

    entries = {entry["path"]: entry for entry in result.manifest["entries"]}
    assert entries["movies.json"]["schema"]["item_keys"] == ["id", "status", "title"]
    assert "Private title" not in json.dumps(result.manifest)
    assert entries[".env"]["classification"] == "excluded_sensitive"
    assert "schema" not in entries[".env"]
    assert "sha256" not in entries[".env"]
    after = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in source.iterdir()}
    assert after == before


def test_inventory_writer_uses_target_only(tmp_path):
    source = tmp_path / "legacy"
    target = tmp_path / "target"
    source.mkdir()
    (source / "reading.json").write_text('{"entries": []}', encoding="utf-8")
    result = build_inventory(source)

    written = write_inventory(result, target)

    assert written["relative_path"] == "legacy-inventory.json"
    assert (target / "legacy-inventory.md").exists()
    assert sorted(path.name for path in source.iterdir()) == ["reading.json"]
