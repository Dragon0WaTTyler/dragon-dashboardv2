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
            "enabled": True,
            "show_in_navigation": False,
            "show_on_home": False,
            "default_view": "watching",
            "default_sort": "recent",
            "feature_recommendation": False,
        },
    )

    saved = json.loads((tmp_path / "control-center.json").read_text(encoding="utf-8"))
    assert saved["schema_version"] == 2
    assert saved["general"]["appearance"] == "system"
    assert saved["sections"]["movies"]["enabled"] is True
    assert saved["sections"]["movies"]["show_in_navigation"] is False
    assert saved["sections"]["movies"]["default_view"] == "watching"
    assert saved["sections"]["movies"]["features"] == {
        "personal_score": False,
        "progress": False,
        "recommendation": False,
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


def test_preference_store_reorders_home_and_resets_one_section(tmp_path):
    store = PreferenceStore(tmp_path)
    store.update_home(
        {
            "layout_order": "favorite_iptv,recommended_movie",
            "home_favorite_iptv_enabled": "on",
            "home_favorite_iptv_limit": "10",
            "home_recommended_movie_enabled": "on",
            "home_recommended_movie_limit": "5",
        }
    )
    store.update(
        "mytv",
        {"enabled": False, "default_view": "favorites", "default_sort": "favorites"},
    )

    preferences = store.read()
    assert [item["section"] for item in preferences["home"]["layout"]][:2] == [
        "favorite_iptv",
        "recommended_movie",
    ]
    assert preferences["home"]["layout"][0]["item_limit"] == 10
    assert preferences["sections"]["mytv"]["enabled"] is False

    store.reset_section("mytv")
    assert store.read()["sections"]["mytv"]["enabled"] is True
