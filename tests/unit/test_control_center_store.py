import json

from app.admin.control_center import PreferenceStore


def test_preference_store_merges_defaults_and_writes_atomically(tmp_path):
    store = PreferenceStore(tmp_path)
    defaults = store.read()
    assert defaults["sections"]["movies"]["show_in_navigation"] is True
    assert defaults["sections"]["movies"]["features"]["recommendation"] is True

    store.update(
        "movies",
        {
            "show_in_navigation": False,
            "show_on_today": False,
            "feature_recommendation": False,
        },
    )

    saved = json.loads((tmp_path / "control-center.json").read_text(encoding="utf-8"))
    assert saved["version"] == 1
    assert saved["sections"]["movies"] == {
        "features": {"recommendation": False},
        "show_in_navigation": False,
        "show_on_today": False,
    }
    assert not list(tmp_path.glob("*.tmp"))


def test_preference_store_ignores_unknown_or_malformed_values(tmp_path):
    (tmp_path / "control-center.json").write_text(
        '{"sections":{"movies":{"show_in_navigation":"no","unknown":true}}}',
        encoding="utf-8",
    )
    preferences = PreferenceStore(tmp_path).read()
    assert preferences["sections"]["movies"]["show_in_navigation"] is True
    assert "unknown" not in preferences["sections"]["movies"]
