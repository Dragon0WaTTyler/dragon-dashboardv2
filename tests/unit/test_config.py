from pathlib import Path

import pytest

from app.config import Settings, parse_bool


def test_boolean_parser_is_strict():
    assert parse_bool("yes", default=False) is True
    assert parse_bool("OFF", default=True) is False
    with pytest.raises(ValueError, match="Invalid boolean"):
        parse_bool("sometimes", default=False)


def test_production_requires_secret(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DRAGON_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="required in production"):
        Settings.load(tmp_path, {"DRAGON_ENV": "production"})


def test_feature_flags_default_safe(tmp_path: Path):
    settings = Settings.load(tmp_path, {"TESTING": True})
    assert settings.auth_required is True
    assert settings.ai_enabled is False
    assert settings.playback_enabled is False
    assert settings.vidsrc_enabled is False
    assert settings.magnets_enabled is False
    assert settings.subtitles_enabled is False
    assert settings.external_sync_enabled is False
    assert settings.notion_writeback_enabled is False
    assert settings.youtube_delete_enabled is False
    assert settings.youtube_sync_enabled is False
    assert settings.reading_tts_enabled is False
    assert settings.vidsrc_embed_url == "https://v2.vidsrc.me/embed"
    assert settings.subtitle_languages == "ar,en"


def test_prefixed_feature_flag_override(tmp_path: Path):
    settings = Settings.load(
        tmp_path,
        {"TESTING": True, "DRAGON_EXTERNAL_SYNC_ENABLED": "true"},
    )
    assert settings.external_sync_enabled is True


def test_vidsrc_configuration_is_typed_and_private(tmp_path: Path):
    settings = Settings.load(
        tmp_path,
        {
            "TESTING": True,
            "DRAGON_VIDSRC_ENABLED": "true",
            "DRAGON_VIDSRC_EMBED_URL": "https://player.example.test/embed/",
            "TMDB_API_KEY": "private-key",
            "TMDB_READ_ACCESS_TOKEN": "private-token",
        },
    )

    assert settings.vidsrc_enabled is True
    assert settings.vidsrc_embed_url == "https://player.example.test/embed"
    assert settings.tmdb_api_key == "private-key"
    assert settings.tmdb_read_access_token == "private-token"
    summary = settings.safe_summary()
    assert "vidsrc_embed_url" not in summary
    assert "tmdb_api_key" not in summary
    assert "tmdb_read_access_token" not in summary

    with pytest.raises(ValueError, match="plain HTTPS base URL"):
        Settings.load(
            tmp_path,
            {
                "TESTING": True,
                "DRAGON_VIDSRC_EMBED_URL": "javascript:alert(1)",
            },
        )


def test_false_boolean_override_wins_over_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DRAGON_EXTERNAL_SYNC_ENABLED", "true")
    settings = Settings.load(
        tmp_path,
        {"TESTING": True, "EXTERNAL_SYNC_ENABLED": False},
    )
    assert settings.external_sync_enabled is False


def test_subdl_key_enables_subtitles_without_entering_safe_summary(tmp_path: Path):
    settings = Settings.load(
        tmp_path,
        {
            "TESTING": True,
            "DRAGON_SUBDL_API_KEY": "private-key",
            "DRAGON_SUBTITLE_LANGUAGES": "ar,en",
        },
    )

    assert settings.subtitles_enabled is True
    assert settings.subdl_api_key == "private-key"
    assert settings.subtitle_languages == "ar,en"
    assert "subdl_api_key" not in settings.safe_summary()


def test_private_youtube_settings_enable_playlist_sync(tmp_path: Path):
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    (secret_root / "youtube_api_key").write_text("private-key", encoding="utf-8")
    (secret_root / "youtube_watch_later_playlist_id").write_text(
        "PL-test-playlist-123", encoding="utf-8"
    )

    settings = Settings.load(tmp_path, {"TESTING": True})

    assert settings.youtube_sync_enabled is True
    assert "youtube_api_key" not in settings.safe_summary()
    assert "youtube_watch_later_playlist_id" not in settings.safe_summary()
