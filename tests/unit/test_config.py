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
    assert settings.pythonanywhere_lite is False
    assert settings.ai_enabled is False
    assert settings.playback_enabled is False
    assert settings.vidsrc_enabled is False
    assert settings.jackett_enabled is False
    assert settings.magnets_enabled is False
    assert settings.playback_cache_gb == 10
    assert settings.playback_cache_ttl_hours == 168
    assert settings.subtitles_enabled is False
    assert settings.external_sync_enabled is False
    assert settings.notion_writeback_enabled is False
    assert settings.youtube_delete_enabled is False
    assert settings.youtube_sync_enabled is False
    assert settings.reading_tts_enabled is False
    assert settings.tv_epg_enabled is True
    assert settings.tv_epg_refresh_minutes == 360
    assert settings.tv_epg_urls == ""
    assert settings.mytv_http_timeout == 15
    assert settings.vidsrc_embed_url == "https://v2.vidsrc.me/embed"
    assert settings.subtitle_languages == "ar,en"


def test_prefixed_feature_flag_override(tmp_path: Path):
    settings = Settings.load(
        tmp_path,
        {"TESTING": True, "DRAGON_EXTERNAL_SYNC_ENABLED": "true"},
    )
    assert settings.external_sync_enabled is True


def test_pythonanywhere_lite_flag_is_typed_and_exposed(tmp_path: Path):
    settings = Settings.load(
        tmp_path,
        {"TESTING": True, "DRAGON_PYTHONANYWHERE_LITE": "true"},
    )

    assert settings.pythonanywhere_lite is True
    assert settings.flask_mapping()["DRAGON_PYTHONANYWHERE_LITE"] is True


def test_tv_epg_configuration_is_typed(tmp_path: Path):
    settings = Settings.load(
        tmp_path,
        {
            "TESTING": True,
            "DRAGON_TV_EPG_ENABLED": "false",
            "DRAGON_TV_EPG_REFRESH_MINUTES": "120",
            "DRAGON_TV_EPG_URLS": "https://guide.example/one.xml",
        },
    )
    assert settings.tv_epg_enabled is False
    assert settings.tv_epg_refresh_minutes == 120
    assert settings.tv_epg_urls == "https://guide.example/one.xml"


def test_mytv_http_timeout_is_typed(tmp_path: Path):
    settings = Settings.load(tmp_path, {"TESTING": True, "DRAGON_MYTV_HTTP_TIMEOUT": "30"})

    assert settings.mytv_http_timeout == 30
    assert settings.flask_mapping()["MYTV_HTTP_TIMEOUT"] == 30
    with pytest.raises(ValueError, match="between 1"):
        Settings.load(tmp_path, {"TESTING": True, "DRAGON_MYTV_HTTP_TIMEOUT": "0"})


def test_playback_cache_limits_are_typed(tmp_path: Path):
    settings = Settings.load(
        tmp_path,
        {
            "TESTING": True,
            "DRAGON_PLAYBACK_CACHE_GB": "25",
            "DRAGON_PLAYBACK_CACHE_TTL_HOURS": "48",
        },
    )
    assert settings.playback_cache_gb == 25
    assert settings.playback_cache_ttl_hours == 48
    with pytest.raises(ValueError, match="between 1"):
        Settings.load(tmp_path, {"TESTING": True, "DRAGON_PLAYBACK_CACHE_GB": "0"})


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


def test_cinesrc_is_an_explicitly_disabled_by_default_direct_provider(tmp_path: Path):
    disabled = Settings.load(tmp_path, {"TESTING": True})
    enabled = Settings.load(
        tmp_path,
        {
            "TESTING": True,
            "DRAGON_CINESRC_ENABLED": "true",
            "DRAGON_VIDCORE_ENABLED": "true",
            "DRAGON_VIDZEE_ENABLED": "true",
            "DRAGON_VIDEM_ENABLED": "true",
            "DRAGON_VIDLOVE_ENABLED": "true",
        },
    )

    assert disabled.cinesrc_enabled is False
    assert disabled.vidlove_enabled is False
    assert enabled.cinesrc_enabled is True
    assert enabled.vidcore_enabled is True
    assert enabled.vidzee_enabled is True
    assert enabled.videm_enabled is True
    assert enabled.vidlove_enabled is True
    assert enabled.safe_summary()["cinesrc_enabled"] is True


def test_multiembed_direct_providers_are_enabled_by_default_and_accept_player_source_aliases(
    tmp_path: Path,
):
    defaults = Settings.load(tmp_path, {"TESTING": True})
    aliases_disabled = Settings.load(
        tmp_path,
        {
            "TESTING": True,
            "PLAYER_SOURCE_MULTIEMBED_ENABLED": "false",
            "PLAYER_SOURCE_MULTIEMBED_VIP_ENABLED": "false",
        },
    )

    assert defaults.multiembed_enabled is True
    assert defaults.multiembed_vip_enabled is True
    assert aliases_disabled.multiembed_enabled is False
    assert aliases_disabled.multiembed_vip_enabled is False


def test_indexed_embed_provider_urls_are_typed_and_private(tmp_path: Path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "streamwish_embed_url").write_text(
        "https://streamwish.com/e/{asset_id}", encoding="utf-8"
    )
    (secrets_dir / "streamwish_api_key").write_text("private-streamwish-key", encoding="utf-8")
    (secrets_dir / "mixdrop_api_email").write_text("private-mixdrop@example.test", encoding="utf-8")
    (secrets_dir / "mixdrop_api_key").write_text("private-mixdrop-key", encoding="utf-8")
    (secrets_dir / "streamtape_api_login").write_text("private-streamtape-login", encoding="utf-8")
    (secrets_dir / "streamtape_api_key").write_text("private-streamtape-key", encoding="utf-8")
    settings = Settings.load(
        tmp_path,
        {
            "TESTING": True,
            "DRAGON_UPDOWN_ENABLED": True,
            "DRAGON_UPDOWN_EMBED_URL": "https://updown.icu/embed-{asset_id}-1280x640.html",
            "DRAGON_STREAMWISH_ENABLED": True,
            "DRAGON_STREAMWISH_LIBRARY_SYNC_ENABLED": True,
            "DRAGON_MIXDROP_ENABLED": True,
            "DRAGON_MIXDROP_EMBED_URL": "https://mixdrop.ag/e/{asset_id}",
            "DRAGON_MIXDROP_LIBRARY_SYNC_ENABLED": True,
            "DRAGON_DOODSTREAM_ENABLED": True,
            "DRAGON_DOODSTREAM_EMBED_URL": "https://dood.to/e/{asset_id}",
            "DRAGON_FILELIONS_ENABLED": True,
            "DRAGON_FILELIONS_EMBED_URL": "https://filelions.to/v/{asset_id}",
            "DRAGON_OK_ENABLED": True,
            "DRAGON_OK_EMBED_URL": "https://ok.ru/videoembed/{asset_id}",
            "DRAGON_STREAMTAPE_ENABLED": True,
            "DRAGON_STREAMTAPE_EMBED_URL": "https://streamtape.com/e/{asset_id}",
            "DRAGON_STREAMTAPE_LIBRARY_SYNC_ENABLED": True,
            "DRAGON_LULUSTREAM_ENABLED": True,
            "DRAGON_LULUSTREAM_EMBED_URL": "https://lulustream.com/e/{asset_id}",
        },
    )

    assert settings.updown_enabled is True
    assert settings.streamwish_enabled is True
    assert settings.streamwish_embed_url == "https://streamwish.com/e/{asset_id}"
    assert settings.streamwish_library_sync_enabled is True
    assert settings.streamwish_api_key == "private-streamwish-key"
    assert settings.mixdrop_enabled is True
    assert settings.mixdrop_embed_url == "https://mixdrop.ag/e/{asset_id}"
    assert settings.mixdrop_library_sync_enabled is True
    assert settings.mixdrop_api_email == "private-mixdrop@example.test"
    assert settings.mixdrop_api_key == "private-mixdrop-key"
    assert settings.doodstream_enabled is True
    assert settings.filelions_enabled is True
    assert settings.ok_enabled is True
    assert settings.streamtape_enabled is True
    assert settings.streamtape_library_sync_enabled is True
    assert settings.streamtape_api_login == "private-streamtape-login"
    assert settings.streamtape_api_key == "private-streamtape-key"
    assert settings.lulustream_enabled is True
    assert "updown_embed_url" not in settings.safe_summary()
    assert "streamwish_embed_url" not in settings.safe_summary()
    assert "streamwish_api_key" not in settings.safe_summary()
    assert "mixdrop_embed_url" not in settings.safe_summary()
    assert "mixdrop_api_email" not in settings.safe_summary()
    assert "mixdrop_api_key" not in settings.safe_summary()
    assert "doodstream_embed_url" not in settings.safe_summary()
    assert "filelions_embed_url" not in settings.safe_summary()
    assert "ok_embed_url" not in settings.safe_summary()
    assert "streamtape_embed_url" not in settings.safe_summary()
    assert "streamtape_api_login" not in settings.safe_summary()
    assert "streamtape_api_key" not in settings.safe_summary()
    assert "lulustream_embed_url" not in settings.safe_summary()


def test_false_boolean_override_wins_over_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DRAGON_EXTERNAL_SYNC_ENABLED", "true")
    settings = Settings.load(
        tmp_path,
        {"TESTING": True, "EXTERNAL_SYNC_ENABLED": False},
    )
    assert settings.external_sync_enabled is False


def test_book_notion_settings_are_separate_from_movie_notion_settings(tmp_path: Path):
    settings = Settings.load(
        tmp_path,
        {
            "TESTING": True,
            "NOTION_TOKEN": "private-token",
            "NOTION_DATABASE_ID": "movie-db",
            "NOTION_BOOKS_DATABASE_ID": "book-db",
        },
    )

    assert settings.notion_database_id == "movie-db"
    assert settings.book_notion_database_id == "book-db"
    assert "book_notion_database_id" not in settings.safe_summary()


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
    assert settings.subtitle_provider == "auto"
    assert settings.subtitle_languages == "ar,en"
    assert "subdl_api_key" not in settings.safe_summary()


def test_wyzie_key_enables_subtitles_without_entering_safe_summary(tmp_path: Path):
    settings = Settings.load(
        tmp_path,
        {
            "TESTING": True,
            "DRAGON_WYZIE_API_KEY": "private-wyzie-key",
            "DRAGON_SUBTITLE_PROVIDER": "wyzie",
        },
    )

    assert settings.subtitles_enabled is True
    assert settings.subtitle_provider == "wyzie"
    assert settings.wyzie_api_key == "private-wyzie-key"
    assert settings.wyzie_base_url == "https://sub.wyzie.io"
    assert "wyzie_api_key" not in settings.safe_summary()


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


def test_private_youtube_oauth_token_enables_sync_and_deletion(tmp_path: Path):
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    (secret_root / "youtube_token.json").write_text("{}", encoding="utf-8")
    (secret_root / "youtube_watch_later_playlist_id").write_text(
        "PL-test-playlist-123", encoding="utf-8"
    )

    settings = Settings.load(tmp_path, {"TESTING": True})

    assert settings.youtube_sync_enabled is True
    assert settings.youtube_delete_enabled is True
