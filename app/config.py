from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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
    auth_required: bool
    ai_enabled: bool
    playback_enabled: bool
    vidsrc_enabled: bool
    vidsrc_embed_url: str
    tmdb_api_key: str
    tmdb_read_access_token: str
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
    notion_sync_enabled: bool
    notion_writeback_enabled: bool
    notion_token: str
    notion_database_id: str
    notion_data_source_id: str
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
        vidsrc_embed_url = _https_base_url(
            str(
                override_map.get("VIDSRC_EMBED_URL")
                or override_map.get("DRAGON_VIDSRC_EMBED_URL")
                or os.getenv("DRAGON_VIDSRC_EMBED_URL", "")
                or "https://v2.vidsrc.me/embed"
            ),
            name="DRAGON_VIDSRC_EMBED_URL",
        )
        tmdb_api_key = str(
            override_map.get("TMDB_API_KEY")
            or override_map.get("DRAGON_TMDB_API_KEY")
            or os.getenv("DRAGON_TMDB_API_KEY", "")
            or os.getenv("TMDB_API_KEY", "")
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
        subtitle_provider = str(
            override_map.get("SUBTITLE_PROVIDER")
            or override_map.get("DRAGON_SUBTITLE_PROVIDER")
            or os.getenv("DRAGON_SUBTITLE_PROVIDER", "")
            or "auto"
        ).strip().lower()
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

        return cls(
            environment=environment,
            secret_key=secret_key,
            database_url=database_url,
            auth_required=feature("AUTH_REQUIRED", True),
            ai_enabled=feature("AI_ENABLED", False),
            playback_enabled=feature("PLAYBACK_ENABLED", False),
            vidsrc_enabled=feature("VIDSRC_ENABLED", False),
            vidsrc_embed_url=vidsrc_embed_url,
            tmdb_api_key=tmdb_api_key,
            tmdb_read_access_token=tmdb_read_access_token,
            jackett_url=jackett_url,
            jackett_api_key=jackett_api_key,
            jackett_min_seeders=positive_integer(
                "JACKETT_MIN_SEEDERS", 5, maximum=100000
            ),
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
            notion_sync_enabled=feature(
                "NOTION_SYNC_ENABLED",
                bool(
                    not is_testing
                    and notion_token
                    and (notion_database_id or notion_data_source_id)
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
            notion_sync_ttl_seconds=positive_integer(
                "NOTION_SYNC_TTL_SECONDS", 120, maximum=86400
            ),
            youtube_delete_enabled=feature("YOUTUBE_DELETE_ENABLED", False),
            youtube_sync_enabled=feature(
                "YOUTUBE_SYNC_ENABLED",
                bool(youtube_api_key and youtube_watch_later_playlist_id),
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
            "DRAGON_TMDB_API_KEY": self.tmdb_api_key,
            "DRAGON_TMDB_READ_ACCESS_TOKEN": self.tmdb_read_access_token,
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
            "DRAGON_NOTION_SYNC_ENABLED": self.notion_sync_enabled,
            "DRAGON_NOTION_WRITEBACK_ENABLED": self.notion_writeback_enabled,
            "DRAGON_NOTION_TOKEN": self.notion_token,
            "DRAGON_NOTION_DATABASE_ID": self.notion_database_id,
            "DRAGON_NOTION_DATA_SOURCE_ID": self.notion_data_source_id,
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
            "tmdb_api_key",
            "tmdb_read_access_token",
            "jackett_url",
            "jackett_api_key",
            "notion_token",
            "notion_database_id",
            "notion_data_source_id",
            "wyzie_api_key",
            "subdl_api_key",
        }
        return {
            field.name: getattr(self, field.name)
            for field in fields(self)
            if field.name not in hidden
        }
