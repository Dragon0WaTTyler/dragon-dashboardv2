from app.mytv import health


def test_health_probe_uses_a_working_alternate(monkeypatch):
    calls = []

    def probe(ffprobe: str, url: str) -> bool:
        assert ffprobe == "ffprobe-test"
        calls.append(url)
        return url.endswith("working.m3u8")

    monkeypatch.setattr(health, "_probe_url", probe)
    result = health._probe_target(
        "ffprobe-test",
        health.HealthTarget(
            preference_key="channel-key",
            candidates=(
                "https://dead-health.example/live.m3u8",
                "https://good.example/working.m3u8",
            ),
        ),
    )

    assert result.online is True
    assert result.source_fingerprint
    assert calls == [
        "https://dead-health.example/live.m3u8",
        "https://good.example/working.m3u8",
    ]
