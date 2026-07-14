import json


def test_migration_inventory_cli_requires_explicit_source(app, tmp_path):
    runner = app.test_cli_runner()
    missing = runner.invoke(args=["migrate", "inventory"])
    assert missing.exit_code != 0

    source = tmp_path / "legacy"
    source.mkdir()
    (source / "items.json").write_text("[]", encoding="utf-8")
    result = runner.invoke(args=["migrate", "inventory", "--source", str(source)])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["counts"]["structured_data"] == 1
    assert payload["status"] == "completed"
