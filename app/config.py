from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    secret_key: str
    database_url: str
    auth_required: bool
    ai_enabled: bool
    playback_enabled: bool
    magnets_enabled: bool
    external_sync_enabled: bool
    notion_writeback_enabled: bool
    youtube_delete_enabled: bool
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

        default_db_path = Path(instance_path) / "dragon.sqlite3"
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

        return cls(
            environment=environment,
            secret_key=secret_key,
            database_url=database_url,
            auth_required=feature("AUTH_REQUIRED", True),
            ai_enabled=feature("AI_ENABLED", False),
            playback_enabled=feature("PLAYBACK_ENABLED", False),
            magnets_enabled=feature("MAGNETS_ENABLED", False),
            external_sync_enabled=feature("EXTERNAL_SYNC_ENABLED", False),
            notion_writeback_enabled=feature("NOTION_WRITEBACK_ENABLED", False),
            youtube_delete_enabled=feature("YOUTUBE_DELETE_ENABLED", False),
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
            "DRAGON_MAGNETS_ENABLED": self.magnets_enabled,
            "DRAGON_EXTERNAL_SYNC_ENABLED": self.external_sync_enabled,
            "DRAGON_NOTION_WRITEBACK_ENABLED": self.notion_writeback_enabled,
            "DRAGON_YOUTUBE_DELETE_ENABLED": self.youtube_delete_enabled,
            "DRAGON_READING_TTS_ENABLED": self.reading_tts_enabled,
        }
        mapping.update(overrides or {})
        return mapping

    def safe_summary(self) -> dict[str, Any]:
        hidden = {"secret_key", "database_url"}
        return {
            field.name: getattr(self, field.name)
            for field in fields(self)
            if field.name not in hidden
        }
