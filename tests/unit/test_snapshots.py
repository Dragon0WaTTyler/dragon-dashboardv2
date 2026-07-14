import json

import pytest

from app.shared.snapshots import SnapshotStore


def test_snapshot_store_writes_and_reads_versioned_payload(tmp_path):
    store = SnapshotStore(tmp_path)
    written = store.write("movies", {"items": [{"id": "mov_1"}]}, schema_version="movies.v1")

    result = store.read("movies", expected_schema="movies.v1")

    assert written["relative_path"] == "movies.json"
    assert len(written["checksum"]) == 64
    assert result.state == "fresh"
    assert result.payload == {"items": [{"id": "mov_1"}]}


def test_snapshot_store_uses_previous_valid_copy_when_latest_is_malformed(tmp_path):
    store = SnapshotStore(tmp_path)
    store.write("reading", {"items": [{"id": "first"}]}, schema_version="reading.v1")
    store.write("reading", {"items": [{"id": "second"}]}, schema_version="reading.v1")
    (tmp_path / "reading.json").write_text("{broken", encoding="utf-8")

    result = store.read("reading", expected_schema="reading.v1")

    assert result.state == "stale"
    assert result.used_previous is True
    assert result.payload == {"items": [{"id": "first"}]}


def test_snapshot_store_reports_missing_and_malformed(tmp_path):
    store = SnapshotStore(tmp_path)
    assert store.read("books").state == "missing"
    (tmp_path / "books.json").write_text(json.dumps({"payload": "wrong"}), encoding="utf-8")
    assert store.read("books").state == "malformed"


def test_snapshot_store_rejects_unsafe_domain(tmp_path):
    store = SnapshotStore(tmp_path)
    with pytest.raises(ValueError):
        store.write("../escape", {}, schema_version="v1")
