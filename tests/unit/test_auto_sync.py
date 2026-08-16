from app.shared.auto_sync import _sync_epg_if_due, _sync_pockettube_if_due


def test_disabled_pockettube_auto_sync_exits_cleanly(app):
    app.config["DRAGON_YOUTUBE_SYNC_ENABLED"] = False

    _sync_pockettube_if_due(app)


def test_due_epg_auto_sync_runs_once(app, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.mytv.epg.EPGSyncService.is_due", staticmethod(lambda: True)
    )
    monkeypatch.setattr(
        "app.mytv.epg.EPGSyncService.sync",
        lambda _self: calls.append("sync") or {"programmes": 2},
    )

    _sync_epg_if_due(app)

    assert calls == ["sync"]
