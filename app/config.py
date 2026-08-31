from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.playback.providers import validate_indexed_embed_url_template

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


def parse_bool(value: str | bool | None, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(f"Invalid boolean configuration value: {value!r}")


def _local_secret(instance_path: Path) -> str:
    secret_path = instance_path / ".secret_key"
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()
    instance_path.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(48)
    secret_path.write_text(value, encoding="utf-8")
    return value


def _private_setting(instance_path: Path, name: str) -> str:
    path = instance_path / "secrets" / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _https_base_url(value: str, *, name: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{name} must be a plain HTTPS base URL.")
    return normalized


def _service_base_url(value: str, *, name: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{name} must be a plain HTTP(S) base URL.")
    return normalized


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    secret_key: str
    database_url: str
    pythonanywhere_lite: bool
    auth_required: bool
    ai_enabled: bool
    playback_enabled: bool
    vidsrc_enabled: bool
    vidsrc_embed_url: str
    vidlove_enabled: bool
    cinesrc_enabled: bool
    vidcore_enabled: bool
    vidzee_enabled: bool
    videm_enabled: bool
    multiembed_enabled: bool
    multiembed_vip_enabled: bool
    videotube_enabled: bool
    videotube_embed_url: str
    updown_enabled: bool
    updown_embed_url: str
    streamwish_enabled: bool
    streamwish_embed_url: str
    streamwish_library_sync_enabled: bool
    streamwish_api_key: str
    mixdrop_enabled: bool
    mixdrop_embed_url: str
    mixdrop_library_sync_enabled: bool
    mixdrop_api_email: str
    mixdrop_api_key: str
    doodstream_enabled: bool
    doodstream_embed_url: str
    doodstream_library_sync_enabled: bool
    doodstream_api_key: str
    filelions_enabled: bool
    filelions_embed_url: str
    filelions_library_sync_enabled: bool
    filelions_api_key: str
    ok_enabled: bool
    ok_embed_url: str
    streamtape_enabled: bool
    streamtape_embed_url: str
    streamtape_library_sync_enabled: bool
    streamtape_api_login: str
    streamtape_api_key: str
    lulustream_enabled: bool
    lulustream_embed_url: str
    lulustream_library_sync_enabled: bool
    lulustream_api_key: str
    uqload_enabled: bool
    uqload_embed_url: str
    tmdb_api_key: str
    tmdb_read_access_token: str
    jackett_enabled: bool
    jackett_url: str
    jackett_api_key: str
    jackett_min_seeders: int
    magnets_enabled: bool
    playback_cache_gb: int
    playback_cache_ttl_hours: int
    subtitles_enabled: bool
    subtitle_provider: str
    wyzie_api_key: str
    wyzie_base_url: str
    subdl_api_key: str
    subtitle_languages: str
    external_sync_enabled: bool
    tv_epg_enabled: bool
    tv_epg_refresh_minutes: int
    tv_epg_urls: str
    mytv_direct_favorites: bool
    mytv_http_timeout: int
    notion_sync_enabled: bool
    notion_writeback_enabled: bool
    notion_token: str
    notion_database_id: str
    notion_data_source_id: str
    book_notion_database_id: str
    book_notion_data_source_id: str
    book_quotes_database_id: str
    book_quotes_data_source_id: str
    notion_tv_show_database_id: str
    notion_tv_show_data_source_id: str
    notion_tv_episode_database_id: str
    notion_tv_episode_data_source_id: str
    notion_sync_ttl_seconds: int
    youtube_delete_enabled: bool
    youtube_sync_enabled: bool
    youtube_api_key: str
    youtube_watch_later_playlist_id: str
    reading_tts_enabled: bool

    @classmethod
    def load(
        cls,
        instance_path: str | Path,
        overrides: Mapping[str, Any] | None = None,
    ) -> Settings:
        override_map = {str(key).upper(): value for key, value in (overrides or {}).items()}
        environment = str(
            override_map.get("ENVIRONMENT")
            or override_map.get("DRAGON_ENV")
            or os.getenv("DRAGON_ENV", "development")
        ).lower()
        is_testing = parse_bool(override_map.get("TESTING"), default=False)
        secret_key = str(
            override_map.get("SECRET_KEY") or os.getenv("DRAGON_SECRET_KEY", "")
        ).strip()
        if not secret_key:
            if environment == "production" and not is_testing:
                raise RuntimeError("DRAGON_SECRET_KEY is required in production.")
            secret_key = "dragon-test-secret" if is_testing else _local_secret(Path(instance_path))

        instance_root = Path(instance_path)
        default_db_path = instance_root / "dragon.sqlite3"
        database_url = str(
            override_map.get("SQLALCHEMY_DATABASE_URI")
            or override_map.get("DATABASE_URL")
            or os.getenv("DRAGON_DATABASE_URL", "")
            or f"sqlite:///{default_db_path.as_posix()}"
        )

        def feature(name: str, default: bool) -> bool:
            value = override_map.get(name)
            if value is None:
                value = override_map.get(f"DRAGON_{name}")
            if value is None:
                value = os.getenv(f"DRAGON_{name}")
            return parse_bool(value, default=default)

        def feature_with_aliases(name: str, default: bool, *aliases: str) -> bool:
            value = override_map.get(name)
            if value is None:
                value = override_map.get(f"DRAGON_{name}")
            if value is None:
                value = os.getenv(f"DRAGON_{name}")
            for alias in aliases:
                if value is not None:
                    break
                value = override_map.get(alias)
                if value is None:
                    value = override_map.get(f"DRAGON_{alias}")
                if value is None:
                    value = os.getenv(alias)
                if value is None:
                    value = os.getenv(f"DRAGON_{alias}")
            return parse_bool(value, default=default)

        def positive_integer(name: str, default: int, *, maximum: int) -> int:
            value = override_map.get(name)
            if value is None:
                value = override_map.get(f"DRAGON_{name}")
            if value is None:
                value = os.getenv(f"DRAGON_{name}")
            if value is None or str(value).strip() == "":
                return default
            try:
                parsed = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"DRAGON_{name} must be a whole number.") from exc
            if parsed < 1 or parsed > maximum:
                raise ValueError(f"DRAGON_{name} must be between 1 and {maximum}.")
            return parsed

        youtube_api_key = str(
            override_map.get("YOUTUBE_API_KEY")
            or override_map.get("DRAGON_YOUTUBE_API_KEY")
            or os.getenv("DRAGON_YOUTUBE_API_KEY", "")
            or os.getenv("YOUTUBE_API_KEY", "")
            or _private_setting(instance_root, "youtube_api_key")
        ).strip()
        youtube_watch_later_playlist_id = str(
            override_map.get("YOUTUBE_WATCH_LATER_PLAYLIST_ID")
            or override_map.get("DRAGON_YOUTUBE_WATCH_LATER_PLAYLIST_ID")
            or os.getenv("DRAGON_YOUTUBE_WATCH_LATER_PLAYLIST_ID", "")
            or _private_setting(instance_root, "youtube_watch_later_playlist_id")
        ).strip()
        youtube_oauth_token_available = (instance_root / "secrets" / "youtube_token.json").is_file()
        vidsrc_embed_url = _https_base_url(
            str(
                override_map.get("VIDSRC_EMBED_URL")
                or override_map.get("DRAGON_VIDSRC_EMBED_URL")
                or os.getenv("DRAGON_VIDSRC_EMBED_URL", "")
                or "https://v2.vidsrc.me/embed"
            ),
            name="DRAGON_VIDSRC_EMBED_URL",
        )

        def optional_indexed_embed_url(provider_key: str) -> str:
            config_key = f"{provider_key.upper()}_EMBED_URL"
            raw = str(
                override_map.get(config_key)
                or override_map.get(f"DRAGON_{config_key}")
                or os.getenv(f"DRAGON_{config_key}", "")
                or _private_setting(instance_root, f"{provider_key}_embed_url")
            ).strip()
            return validate_indexed_embed_url_template(provider_key, raw) if raw else ""

        videotube_embed_url = optional_indexed_embed_url("videotube")
        updown_embed_url = optional_indexed_embed_url("updown")
        streamwish_embed_url = optional_indexed_embed_url("streamwish")
        mixdrop_embed_url = optional_indexed_embed_url("mixdrop")
        doodstream_embed_url = optional_indexed_embed_url("doodstream")
        filelions_embed_url = optional_indexed_embed_url("filelions")
        ok_embed_url = optional_indexed_embed_url("ok")
        streamtape_embed_url = optional_indexed_embed_url("streamtape")
        lulustream_embed_url = optional_indexed_embed_url("lulustream")
        uqload_embed_url = optional_indexed_embed_url("uqload")
        tmdb_api_key = str(
            override_map.get("TMDB_API_KEY")
            or override_map.get("DRAGON_TMDB_API_KEY")
            or os.getenv("DRAGON_TMDB_API_KEY", "")
            or os.getenv("TMDB_API_KEY", "")
        ).strip()
        streamwish_api_key = str(
            override_map.get("STREAMWISH_API_KEY")
            or override_map.get("DRAGON_STREAMWISH_API_KEY")
            or os.getenv("DRAGON_STREAMWISH_API_KEY", "")
            or _private_setting(instance_root, "streamwish_api_key")
        ).strip()
        streamtape_api_login = str(
            override_map.get("STREAMTAPE_API_LOGIN")
            or override_map.get("DRAGON_STREAMTAPE_API_LOGIN")
            or os.getenv("DRAGON_STREAMTAPE_API_LOGIN", "")
            or _private_setting(instance_root, "streamtape_api_login")
        ).strip()
        streamtape_api_key = str(
            override_map.get("STREAMTAPE_API_KEY")
            or override_map.get("DRAGON_STREAMTAPE_API_KEY")
            or os.getenv("DRAGON_STREAMTAPE_API_KEY", "")
            or _private_setting(instance_root, "streamtape_api_key")
        ).strip()
        filelions_api_key = str(
            override_map.get("FILELIONS_API_KEY")
            or override_map.get("DRAGON_FILELIONS_API_KEY")
            or os.getenv("DRAGON_FILELIONS_API_KEY", "")
            or _private_setting(instance_root, "filelions_api_key")
        ).strip()
        doodstream_api_key = str(
            override_map.get("DOODSTREAM_API_KEY")
            or override_map.get("DRAGON_DOODSTREAM_API_KEY")
            or os.getenv("DRAGON_DOODSTREAM_API_KEY", "")
            or _private_setting(instance_root, "doodstream_api_key")
        ).strip()
        lulustream_api_key = str(
            override_map.get("LULUSTREAM_API_KEY")
            or override_map.get("DRAGON_LULUSTREAM_API_KEY")
            or os.getenv("DRAGON_LULUSTREAM_API_KEY", "")
            or _private_setting(instance_root, "lulustream_api_key")
        ).strip()
        mixdrop_api_email = str(
            override_map.get("MIXDROP_API_EMAIL")
            or override_map.get("DRAGON_MIXDROP_API_EMAIL")
            or os.getenv("DRAGON_MIXDROP_API_EMAIL", "")
            or _private_setting(instance_root, "mixdrop_api_email")
        ).strip()
        mixdrop_api_key = str(
            override_map.get("MIXDROP_API_KEY")
            or override_map.get("DRAGON_MIXDROP_API_KEY")
            or os.getenv("DRAGON_MIXDROP_API_KEY", "")
            or _private_setting(instance_root, "mixdrop_api_key")
        ).strip()
        tmdb_read_access_token = str(
            override_map.get("TMDB_READ_ACCESS_TOKEN")
            or override_map.get("DRAGON_TMDB_READ_ACCESS_TOKEN")
            or os.getenv("DRAGON_TMDB_READ_ACCESS_TOKEN", "")
            or os.getenv("TMDB_READ_ACCESS_TOKEN", "")
        ).strip()
        jackett_url = _service_base_url(
            str(
                override_map.get("JACKETT_URL")
                or override_map.get("DRAGON_JACKETT_URL")
                or os.getenv("DRAGON_JACKETT_URL", "")
                or os.getenv("JACKETT_URL", "")
                or "http://127.0.0.1:9117"
            ),
            name="DRAGON_JACKETT_URL",
        )
        jackett_api_key = str(
            override_map.get("JACKETT_API_KEY")
            or override_map.get("DRAGON_JACKETT_API_KEY")
            or os.getenv("DRAGON_JACKETT_API_KEY", "")
            or os.getenv("JACKETT_API_KEY", "")
        ).strip()
        notion_token = str(
            override_map.get("NOTION_TOKEN")
            or override_map.get("DRAGON_NOTION_TOKEN")
            or os.getenv("DRAGON_NOTION_TOKEN", "")
            or os.getenv("NOTION_TOKEN", "")
        ).strip()
        notion_database_id = str(
            override_map.get("NOTION_DATABASE_ID")
            or override_map.get("DRAGON_NOTION_DATABASE_ID")
            or os.getenv("DRAGON_NOTION_DATABASE_ID", "")
            or os.getenv("NOTION_DATABASE_ID", "")
        ).strip()
        notion_data_source_id = str(
            override_map.get("NOTION_DATA_SOURCE_ID")
            or override_map.get("DRAGON_NOTION_DATA_SOURCE_ID")
            or os.getenv("DRAGON_NOTION_DATA_SOURCE_ID", "")
            or os.getenv("NOTION_DATA_SOURCE_ID", "")
        ).strip()
        book_notion_database_id = str(
            override_map.get("BOOK_NOTION_DATABASE_ID")
            or override_map.get("DRAGON_BOOK_NOTION_DATABASE_ID")
            or override_map.get("NOTION_BOOKS_DATABASE_ID")
            or os.getenv("DRAGON_BOOK_NOTION_DATABASE_ID", "")
            or os.getenv("BOOK_NOTION_DATABASE_ID", "")
            or os.getenv("NOTION_BOOKS_DATABASE_ID", "")
        ).strip()
        book_notion_data_source_id = str(
            override_map.get("BOOK_NOTION_DATA_SOURCE_ID")
            or override_map.get("DRAGON_BOOK_NOTION_DATA_SOURCE_ID")
            or override_map.get("NOTION_BOOKS_DATA_SOURCE_ID")
            or os.getenv("DRAGON_BOOK_NOTION_DATA_SOURCE_ID", "")
            or os.getenv("BOOK_NOTION_DATA_SOURCE_ID", "")
            or os.getenv("NOTION_BOOKS_DATA_SOURCE_ID", "")
        ).strip()
        book_quotes_database_id = str(
            override_map.get("BOOK_QUOTES_DATABASE_ID")
            or override_map.get("DRAGON_BOOK_QUOTES_DATABASE_ID")
            or override_map.get("NOTION_BOOK_QUOTES_DATABASE_ID")
            or os.getenv("DRAGON_BOOK_QUOTES_DATABASE_ID", "")
            or os.getenv("BOOK_QUOTES_DATABASE_ID", "")
            or os.getenv("NOTION_BOOK_QUOTES_DATABASE_ID", "")
        ).strip()
        book_quotes_data_source_id = str(
            override_map.get("BOOK_QUOTES_DATA_SOURCE_ID")
            or override_map.get("DRAGON_BOOK_QUOTES_DATA_SOURCE_ID")
            or override_map.get("NOTION_BOOK_QUOTES_DATA_SOURCE_ID")
            or os.getenv("DRAGON_BOOK_QUOTES_DATA_SOURCE_ID", "")
            or os.getenv("BOOK_QUOTES_DATA_SOURCE_ID", "")
            or os.getenv("NOTION_BOOK_QUOTES_DATA_SOURCE_ID", "")
        ).strip()
        notion_tv_show_database_id = str(
            override_map.get("NOTION_TV_SHOW_DATABASE_ID")
            or override_map.get("DRAGON_NOTION_TV_SHOW_DATABASE_ID")
            or os.getenv("DRAGON_NOTION_TV_SHOW_DATABASE_ID", "")
        ).strip()
        notion_tv_show_data_source_id = str(
            override_map.get("NOTION_TV_SHOW_DATA_SOURCE_ID")
            or override_map.get("DRAGON_NOTION_TV_SHOW_DATA_SOURCE_ID")
            or os.getenv("DRAGON_NOTION_TV_SHOW_DATA_SOURCE_ID", "")
        ).strip()
        notion_tv_episode_database_id = str(
            override_map.get("NOTION_TV_EPISODE_DATABASE_ID")
            or override_map.get("DRAGON_NOTION_TV_EPISODE_DATABASE_ID")
            or os.getenv("DRAGON_NOTION_TV_EPISODE_DATABASE_ID", "")
        ).strip()
        notion_tv_episode_data_source_id = str(
            override_map.get("NOTION_TV_EPISODE_DATA_SOURCE_ID")
            or override_map.get("DRAGON_NOTION_TV_EPISODE_DATA_SOURCE_ID")
            or os.getenv("DRAGON_NOTION_TV_EPISODE_DATA_SOURCE_ID", "")
        ).strip()
        subdl_api_key = str(
            override_map.get("SUBDL_API_KEY")
            or override_map.get("DRAGON_SUBDL_API_KEY")
            or os.getenv("DRAGON_SUBDL_API_KEY", "")
            or _private_setting(instance_root, "subdl_api_key")
        ).strip()
        wyzie_api_key = str(
            override_map.get("WYZIE_API_KEY")
            or override_map.get("DRAGON_WYZIE_API_KEY")
            or os.getenv("DRAGON_WYZIE_API_KEY", "")
            or _private_setting(instance_root, "wyzie_api_key")
        ).strip()
        subtitle_provider = (
            str(
                override_map.get("SUBTITLE_PROVIDER")
                or override_map.get("DRAGON_SUBTITLE_PROVIDER")
                or os.getenv("DRAGON_SUBTITLE_PROVIDER", "")
                or "auto"
            )
            .strip()
            .lower()
        )
        if subtitle_provider not in {"auto", "wyzie", "subdl"}:
            raise ValueError("DRAGON_SUBTITLE_PROVIDER must be auto, wyzie, or subdl.")
        wyzie_base_url = _service_base_url(
            str(
                override_map.get("WYZIE_BASE_URL")
                or override_map.get("DRAGON_WYZIE_BASE_URL")
                or os.getenv("DRAGON_WYZIE_BASE_URL", "")
                or "https://sub.wyzie.io"
            ),
            name="DRAGON_WYZIE_BASE_URL",
        )
        subtitle_languages = str(
            override_map.get("SUBTITLE_LANGUAGES")
            or override_map.get("DRAGON_SUBTITLE_LANGUAGES")
            or os.getenv("DRAGON_SUBTITLE_LANGUAGES", "")
            or "ar,en"
        ).strip()
        tv_epg_urls = str(
            override_map.get("TV_EPG_URLS")
            or override_map.get("DRAGON_TV_EPG_URLS")
            or os.getenv("DRAGON_TV_EPG_URLS", "")
        ).strip()

        return cls(
            environment=environment,
            secret_key=secret_key,
            database_url=database_url,
            pythonanywhere_lite=feature("PYTHONANYWHERE_LITE", False),
            auth_required=feature("AUTH_REQUIRED", True),
            ai_enabled=feature("AI_ENABLED", False),
            playback_enabled=feature("PLAYBACK_ENABLED", False),
            vidsrc_enabled=feature("VIDSRC_ENABLED", False),
            vidsrc_embed_url=vidsrc_embed_url,
            vidlove_enabled=feature("VIDLOVE_ENABLED", False),
            cinesrc_enabled=feature("CINESRC_ENABLED", False),
            vidcore_enabled=feature("VIDCORE_ENABLED", False),
            vidzee_enabled=feature("VIDZEE_ENABLED", False),
            videm_enabled=feature("VIDEM_ENABLED", False),
            multiembed_enabled=feature_with_aliases(
                "MULTIEMBED_ENABLED", True, "PLAYER_SOURCE_MULTIEMBED_ENABLED"
            ),
            multiembed_vip_enabled=feature_with_aliases(
                "MULTIEMBED_VIP_ENABLED", True, "PLAYER_SOURCE_MULTIEMBED_VIP_ENABLED"
            ),
            videotube_enabled=feature("VIDEOTUBE_ENABLED", False),
            videotube_embed_url=videotube_embed_url,
            updown_enabled=feature("UPDOWN_ENABLED", False),
            updown_embed_url=updown_embed_url,
            streamwish_enabled=feature("STREAMWISH_ENABLED", False),
            streamwish_embed_url=streamwish_embed_url,
            streamwish_library_sync_enabled=feature("STREAMWISH_LIBRARY_SYNC_ENABLED", False),
            streamwish_api_key=streamwish_api_key,
            mixdrop_enabled=feature("MIXDROP_ENABLED", False),
            mixdrop_embed_url=mixdrop_embed_url,
            mixdrop_library_sync_enabled=feature("MIXDROP_LIBRARY_SYNC_ENABLED", False),
            mixdrop_api_email=mixdrop_api_email,
            mixdrop_api_key=mixdrop_api_key,
            doodstream_enabled=feature("DOODSTREAM_ENABLED", False),
            doodstream_embed_url=doodstream_embed_url,
            doodstream_library_sync_enabled=feature("DOODSTREAM_LIBRARY_SYNC_ENABLED", False),
            doodstream_api_key=doodstream_api_key,
            filelions_enabled=feature("FILELIONS_ENABLED", False),
            filelions_embed_url=filelions_embed_url,
            filelions_library_sync_enabled=feature("FILELIONS_LIBRARY_SYNC_ENABLED", False),
            filelions_api_key=filelions_api_key,
            ok_enabled=feature("OK_ENABLED", False),
            ok_embed_url=ok_embed_url,
            streamtape_enabled=feature("STREAMTAPE_ENABLED", False),
            streamtape_embed_url=streamtape_embed_url,
            streamtape_library_sync_enabled=feature("STREAMTAPE_LIBRARY_SYNC_ENABLED", False),
            streamtape_api_login=streamtape_api_login,
            streamtape_api_key=streamtape_api_key,
            lulustream_enabled=feature("LULUSTREAM_ENABLED", False),
            lulustream_embed_url=lulustream_embed_url,
            lulustream_library_sync_enabled=feature("LULUSTREAM_LIBRARY_SYNC_ENABLED", False),
            lulustream_api_key=lulustream_api_key,
            uqload_enabled=feature("UQLOAD_ENABLED", False),
            uqload_embed_url=uqload_embed_url,
            tmdb_api_key=tmdb_api_key,
            tmdb_read_access_token=tmdb_read_access_token,
            jackett_enabled=feature("JACKETT_ENABLED", False),
            jackett_url=jackett_url,
            jackett_api_key=jackett_api_key,
            jackett_min_seeders=positive_integer("JACKETT_MIN_SEEDERS", 5, maximum=100000),
            magnets_enabled=feature("MAGNETS_ENABLED", False),
            playback_cache_gb=positive_integer("PLAYBACK_CACHE_GB", 10, maximum=1000),
            playback_cache_ttl_hours=positive_integer(
                "PLAYBACK_CACHE_TTL_HOURS", 168, maximum=8760
            ),
            subtitles_enabled=feature("SUBTITLES_ENABLED", bool(wyzie_api_key or subdl_api_key)),
            subtitle_provider=subtitle_provider,
            wyzie_api_key=wyzie_api_key,
            wyzie_base_url=wyzie_base_url,
            subdl_api_key=subdl_api_key,
            subtitle_languages=subtitle_languages,
            external_sync_enabled=feature("EXTERNAL_SYNC_ENABLED", False),
            tv_epg_enabled=feature("TV_EPG_ENABLED", True),
            tv_epg_refresh_minutes=positive_integer(
                "TV_EPG_REFRESH_MINUTES", 360, maximum=1440
            ),
            tv_epg_urls=tv_epg_urls,
            mytv_direct_favorites=feature("MYTV_DIRECT_FAVORITES", False),
            mytv_http_timeout=positive_integer("MYTV_HTTP_TIMEOUT", 15, maximum=120),
            notion_sync_enabled=feature(
                "NOTION_SYNC_ENABLED",
                bool(
                    not is_testing
                    and notion_token
                    and (
                        notion_database_id
                        or notion_data_source_id
                        or book_notion_database_id
                        or book_notion_data_source_id
                    )
                ),
            ),
            notion_writeback_enabled=feature(
                "NOTION_WRITEBACK_ENABLED",
                bool(
                    not is_testing
                    and notion_token
                    and (notion_database_id or notion_data_source_id)
                ),
            ),
            notion_token=notion_token,
            notion_database_id=notion_database_id,
            notion_data_source_id=notion_data_source_id,
            book_notion_database_id=book_notion_database_id,
            book_notion_data_source_id=book_notion_data_source_id,
            book_quotes_database_id=book_quotes_database_id,
            book_quotes_data_source_id=book_quotes_data_source_id,
            notion_tv_show_database_id=notion_tv_show_database_id,
            notion_tv_show_data_source_id=notion_tv_show_data_source_id,
            notion_tv_episode_database_id=notion_tv_episode_database_id,
            notion_tv_episode_data_source_id=notion_tv_episode_data_source_id,
            notion_sync_ttl_seconds=positive_integer("NOTION_SYNC_TTL_SECONDS", 120, maximum=86400),
            youtube_delete_enabled=feature("YOUTUBE_DELETE_ENABLED", youtube_oauth_token_available),
            youtube_sync_enabled=feature(
                "YOUTUBE_SYNC_ENABLED",
                bool(
                    youtube_watch_later_playlist_id
                    and (youtube_api_key or youtube_oauth_token_available)
                ),
            ),
            youtube_api_key=youtube_api_key,
            youtube_watch_later_playlist_id=youtube_watch_later_playlist_id,
            reading_tts_enabled=feature("READING_TTS_ENABLED", False),
        )

    def flask_mapping(self, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
        mapping: dict[str, Any] = {
            "ENVIRONMENT": self.environment,
            "SECRET_KEY": self.secret_key,
            "SQLALCHEMY_DATABASE_URI": self.database_url,
            "DRAGON_PYTHONANYWHERE_LITE": self.pythonanywhere_lite,
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SAMESITE": "Lax",
            "SESSION_COOKIE_SECURE": self.environment == "production",
            "REMEMBER_COOKIE_HTTPONLY": True,
            "REMEMBER_COOKIE_SAMESITE": "Lax",
            "REMEMBER_COOKIE_SECURE": self.environment == "production",
            "WTF_CSRF_TIME_LIMIT": 3600,
            "DRAGON_AUTH_REQUIRED": self.auth_required,
            "DRAGON_AI_ENABLED": self.ai_enabled,
            "DRAGON_PLAYBACK_ENABLED": self.playback_enabled,
            "DRAGON_VIDSRC_ENABLED": self.vidsrc_enabled,
            "DRAGON_VIDSRC_EMBED_URL": self.vidsrc_embed_url,
            "DRAGON_VIDLOVE_ENABLED": self.vidlove_enabled,
            "DRAGON_CINESRC_ENABLED": self.cinesrc_enabled,
            "DRAGON_VIDCORE_ENABLED": self.vidcore_enabled,
            "DRAGON_VIDZEE_ENABLED": self.vidzee_enabled,
            "DRAGON_VIDEM_ENABLED": self.videm_enabled,
            "DRAGON_MULTIEMBED_ENABLED": self.multiembed_enabled,
            "DRAGON_MULTIEMBED_VIP_ENABLED": self.multiembed_vip_enabled,
            "DRAGON_VIDEOTUBE_ENABLED": self.videotube_enabled,
            "DRAGON_VIDEOTUBE_EMBED_URL": self.videotube_embed_url,
            "DRAGON_UPDOWN_ENABLED": self.updown_enabled,
            "DRAGON_UPDOWN_EMBED_URL": self.updown_embed_url,
            "DRAGON_STREAMWISH_ENABLED": self.streamwish_enabled,
            "DRAGON_STREAMWISH_EMBED_URL": self.streamwish_embed_url,
            "DRAGON_STREAMWISH_LIBRARY_SYNC_ENABLED": self.streamwish_library_sync_enabled,
            "DRAGON_STREAMWISH_API_KEY": self.streamwish_api_key,
            "DRAGON_MIXDROP_ENABLED": self.mixdrop_enabled,
            "DRAGON_MIXDROP_EMBED_URL": self.mixdrop_embed_url,
            "DRAGON_MIXDROP_LIBRARY_SYNC_ENABLED": self.mixdrop_library_sync_enabled,
            "DRAGON_MIXDROP_API_EMAIL": self.mixdrop_api_email,
            "DRAGON_MIXDROP_API_KEY": self.mixdrop_api_key,
            "DRAGON_DOODSTREAM_ENABLED": self.doodstream_enabled,
            "DRAGON_DOODSTREAM_EMBED_URL": self.doodstream_embed_url,
            "DRAGON_DOODSTREAM_LIBRARY_SYNC_ENABLED": self.doodstream_library_sync_enabled,
            "DRAGON_DOODSTREAM_API_KEY": self.doodstream_api_key,
            "DRAGON_FILELIONS_ENABLED": self.filelions_enabled,
            "DRAGON_FILELIONS_EMBED_URL": self.filelions_embed_url,
            "DRAGON_FILELIONS_LIBRARY_SYNC_ENABLED": self.filelions_library_sync_enabled,
            "DRAGON_FILELIONS_API_KEY": self.filelions_api_key,
            "DRAGON_OK_ENABLED": self.ok_enabled,
            "DRAGON_OK_EMBED_URL": self.ok_embed_url,
            "DRAGON_STREAMTAPE_ENABLED": self.streamtape_enabled,
            "DRAGON_STREAMTAPE_EMBED_URL": self.streamtape_embed_url,
            "DRAGON_STREAMTAPE_LIBRARY_SYNC_ENABLED": self.streamtape_library_sync_enabled,
            "DRAGON_STREAMTAPE_API_LOGIN": self.streamtape_api_login,
            "DRAGON_STREAMTAPE_API_KEY": self.streamtape_api_key,
            "DRAGON_LULUSTREAM_ENABLED": self.lulustream_enabled,
            "DRAGON_LULUSTREAM_EMBED_URL": self.lulustream_embed_url,
            "DRAGON_LULUSTREAM_LIBRARY_SYNC_ENABLED": self.lulustream_library_sync_enabled,
            "DRAGON_LULUSTREAM_API_KEY": self.lulustream_api_key,
            "DRAGON_UQLOAD_ENABLED": self.uqload_enabled,
            "DRAGON_UQLOAD_EMBED_URL": self.uqload_embed_url,
            "DRAGON_TMDB_API_KEY": self.tmdb_api_key,
            "DRAGON_TMDB_READ_ACCESS_TOKEN": self.tmdb_read_access_token,
            "DRAGON_JACKETT_ENABLED": self.jackett_enabled,
            "DRAGON_JACKETT_URL": self.jackett_url,
            "DRAGON_JACKETT_API_KEY": self.jackett_api_key,
            "DRAGON_JACKETT_MIN_SEEDERS": self.jackett_min_seeders,
            "DRAGON_MAGNETS_ENABLED": self.magnets_enabled,
            "DRAGON_PLAYBACK_CACHE_GB": self.playback_cache_gb,
            "DRAGON_PLAYBACK_CACHE_TTL_HOURS": self.playback_cache_ttl_hours,
            "DRAGON_SUBTITLES_ENABLED": self.subtitles_enabled,
            "DRAGON_SUBTITLE_PROVIDER": self.subtitle_provider,
            "DRAGON_WYZIE_API_KEY": self.wyzie_api_key,
            "DRAGON_WYZIE_BASE_URL": self.wyzie_base_url,
            "DRAGON_SUBDL_API_KEY": self.subdl_api_key,
            "DRAGON_SUBTITLE_LANGUAGES": self.subtitle_languages,
            "DRAGON_EXTERNAL_SYNC_ENABLED": self.external_sync_enabled,
            "DRAGON_TV_EPG_ENABLED": self.tv_epg_enabled,
            "DRAGON_TV_EPG_REFRESH_MINUTES": self.tv_epg_refresh_minutes,
            "DRAGON_TV_EPG_URLS": self.tv_epg_urls,
            "DRAGON_MYTV_DIRECT_FAVORITES": self.mytv_direct_favorites,
            "MYTV_HTTP_TIMEOUT": self.mytv_http_timeout,
            "DRAGON_NOTION_SYNC_ENABLED": self.notion_sync_enabled,
            "DRAGON_NOTION_WRITEBACK_ENABLED": self.notion_writeback_enabled,
            "DRAGON_NOTION_TOKEN": self.notion_token,
            "DRAGON_NOTION_DATABASE_ID": self.notion_database_id,
            "DRAGON_NOTION_DATA_SOURCE_ID": self.notion_data_source_id,
            "DRAGON_BOOK_NOTION_DATABASE_ID": self.book_notion_database_id,
            "DRAGON_BOOK_NOTION_DATA_SOURCE_ID": self.book_notion_data_source_id,
            "DRAGON_BOOK_QUOTES_DATABASE_ID": self.book_quotes_database_id,
            "DRAGON_BOOK_QUOTES_DATA_SOURCE_ID": self.book_quotes_data_source_id,
            "DRAGON_NOTION_TV_SHOW_DATABASE_ID": self.notion_tv_show_database_id,
            "DRAGON_NOTION_TV_SHOW_DATA_SOURCE_ID": self.notion_tv_show_data_source_id,
            "DRAGON_NOTION_TV_EPISODE_DATABASE_ID": self.notion_tv_episode_database_id,
            "DRAGON_NOTION_TV_EPISODE_DATA_SOURCE_ID": self.notion_tv_episode_data_source_id,
            "DRAGON_NOTION_SYNC_TTL_SECONDS": self.notion_sync_ttl_seconds,
            "DRAGON_YOUTUBE_DELETE_ENABLED": self.youtube_delete_enabled,
            "DRAGON_YOUTUBE_SYNC_ENABLED": self.youtube_sync_enabled,
            "DRAGON_YOUTUBE_API_KEY": self.youtube_api_key,
            "DRAGON_YOUTUBE_WATCH_LATER_PLAYLIST_ID": self.youtube_watch_later_playlist_id,
            "DRAGON_READING_TTS_ENABLED": self.reading_tts_enabled,
        }
        mapping.update(overrides or {})
        return mapping

    def safe_summary(self) -> dict[str, Any]:
        hidden = {
            "secret_key",
            "database_url",
            "youtube_api_key",
            "youtube_watch_later_playlist_id",
            "vidsrc_embed_url",
            "videotube_embed_url",
            "updown_embed_url",
            "streamwish_embed_url",
            "streamwish_api_key",
            "mixdrop_embed_url",
            "mixdrop_api_email",
            "mixdrop_api_key",
            "doodstream_embed_url",
            "doodstream_api_key",
            "filelions_embed_url",
            "filelions_api_key",
            "ok_embed_url",
            "streamtape_embed_url",
            "streamtape_api_login",
            "streamtape_api_key",
            "lulustream_embed_url",
            "lulustream_api_key",
            "uqload_embed_url",
            "tmdb_api_key",
            "tmdb_read_access_token",
            "jackett_url",
            "jackett_api_key",
            "notion_token",
            "notion_database_id",
            "notion_data_source_id",
            "book_notion_database_id",
            "book_notion_data_source_id",
            "book_quotes_database_id",
            "book_quotes_data_source_id",
            "notion_tv_show_database_id",
            "notion_tv_show_data_source_id",
            "notion_tv_episode_database_id",
            "notion_tv_episode_data_source_id",
            "wyzie_api_key",
            "subdl_api_key",
        }
        return {
            field.name: getattr(self, field.name)
            for field in fields(self)
            if field.name not in hidden
        }
