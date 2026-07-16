from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flask import current_app, g
from sqlalchemy import MetaData, Table, func, inspect

from app.extensions import db
from app.playback.runtime import build_playback_manager
from app.shared.freshness import get_freshness
from app.shared.models import Operation


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    key: str
    label: str
    description: str
    default: bool = True


@dataclass(frozen=True, slots=True)
class SectionDefinition:
    key: str
    label: str
    description: str
    endpoint: str
    table: str | None = None
    freshness_domains: tuple[str, ...] = ()
    operation_domain: str | None = None
    show_on_today: bool = False
    features: tuple[FeatureDefinition, ...] = field(default_factory=tuple)


SECTIONS: tuple[SectionDefinition, ...] = (
    SectionDefinition(
        "today",
        "Today",
        "The live home workspace assembled from your local queues.",
        "core.index",
        features=(
            FeatureDefinition("freshness", "Freshness warnings", "Show data-health warnings."),
        ),
    ),
    SectionDefinition(
        "movies",
        "Movies",
        "Local watch library, recommendations, playback, and progress.",
        "movies.index",
        "movies",
        ("movies",),
        "movies",
        True,
        (
            FeatureDefinition(
                "recommendation", "What should I watch?", "Show the recommendation engine."
            ),
        ),
    ),
    SectionDefinition(
        "mytv",
        "My TV",
        "Live channel packages and local playback controls.",
        "mytv.index",
        "tv_channels",
    ),
    SectionDefinition(
        "youtube",
        "YouTube",
        "Watch Later and PocketTube videos cached for private browsing.",
        "youtube.index",
        "youtube_videos",
        ("youtube_watch_later", "youtube_pockettube"),
        "youtube_watch_later",
        True,
        (
            FeatureDefinition(
                "description", "Video description", "Show the organized description and chapters."
            ),
            FeatureDefinition(
                "related", "Continue watching", "Show related videos on the detail page."
            ),
        ),
    ),
    SectionDefinition(
        "reading",
        "Reading",
        "Articles, full-text extraction, and source monitoring.",
        "reading.index",
        "articles",
        ("reading",),
        "reading",
        True,
        (
            FeatureDefinition(
                "source_health", "Source health strip", "Show feed health above the article list."
            ),
        ),
    ),
    SectionDefinition(
        "books",
        "Books",
        "Personal library, covers, reading progress, and quotes.",
        "books.index",
        "books",
        ("books",),
        "books",
        True,
        (FeatureDefinition("quotes", "Quotes notebook", "Show saved quotes and the quote form."),),
    ),
    SectionDefinition(
        "chess",
        "Chess",
        "Games, puzzles, courses, and deliberate practice.",
        "chess.index",
        "chess_puzzles",
        ("chess",),
        "chess",
        True,
        (FeatureDefinition("recent_games", "Recent games", "Show the recent-games review table."),),
    ),
    SectionDefinition(
        "german", "German", "Learning resources and vocabulary.", "german.index", "german_resources"
    ),
    SectionDefinition(
        "history",
        "History",
        "A local timeline of activity across Dragon.",
        "history.index",
        "history_events",
    ),
    SectionDefinition("ai", "AI", "Optional contextual workspaces and assistance.", "ai.workspace"),
)

SECTION_MAP = {section.key: section for section in SECTIONS}


class PreferenceStore:
    version = 1

    def __init__(self, root: str | Path):
        self.path = Path(root).resolve() / "control-center.json"

    @staticmethod
    def defaults() -> dict[str, Any]:
        return {
            "version": PreferenceStore.version,
            "sections": {
                section.key: {
                    "show_in_navigation": True,
                    "show_on_today": section.show_on_today,
                    "features": {feature.key: feature.default for feature in section.features},
                }
                for section in SECTIONS
            },
        }

    def read(self) -> dict[str, Any]:
        defaults = self.defaults()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return defaults
        if not isinstance(raw, dict) or not isinstance(raw.get("sections"), dict):
            return defaults
        for section in SECTIONS:
            saved = raw["sections"].get(section.key)
            if not isinstance(saved, dict):
                continue
            target = defaults["sections"][section.key]
            for key in ("show_in_navigation", "show_on_today"):
                if isinstance(saved.get(key), bool):
                    target[key] = saved[key]
            features = saved.get("features")
            if isinstance(features, dict):
                for feature in section.features:
                    if isinstance(features.get(feature.key), bool):
                        target["features"][feature.key] = features[feature.key]
        return defaults

    def update(self, section_key: str, values: dict[str, bool]) -> dict[str, Any]:
        section = SECTION_MAP.get(section_key)
        if section is None:
            raise ValueError("Unknown section.")
        payload = self.read()
        target = payload["sections"][section.key]
        target["show_in_navigation"] = bool(values.get("show_in_navigation"))
        target["show_on_today"] = (
            bool(values.get("show_on_today")) if section.show_on_today else False
        )
        target["features"] = {
            feature.key: bool(values.get(f"feature_{feature.key}")) for feature in section.features
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=".control-center-", suffix=".tmp", dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return payload


def preference_store() -> PreferenceStore:
    root = current_app.config.get("DRAGON_CONTROL_CENTER_ROOT", current_app.instance_path)
    return PreferenceStore(root)


def section_visible(section_key: str) -> bool:
    section = _request_preferences()["sections"].get(section_key, {})
    return bool(section.get("show_in_navigation", True))


def feature_enabled(section_key: str, feature_key: str) -> bool:
    section = _request_preferences()["sections"].get(section_key, {})
    if feature_key == "today":
        return bool(section.get("show_on_today", False))
    return bool(section.get("features", {}).get(feature_key, True))


def _request_preferences() -> dict[str, Any]:
    if "dragon_control_center_preferences" not in g:
        g.dragon_control_center_preferences = preference_store().read()
    return g.dragon_control_center_preferences


def _table_count(table_name: str | None) -> int | None:
    if not table_name or not inspect(db.engine).has_table(table_name):
        return None
    table = Table(table_name, MetaData(), autoload_with=db.engine)
    return int(db.session.scalar(db.select(func.count()).select_from(table)) or 0)


def _capabilities(section: SectionDefinition) -> list[dict[str, Any]]:
    config = current_app.config
    mapping: dict[str, tuple[tuple[str, ...], str]] = {
        "movies": (("DRAGON_PLAYBACK_ENABLED", "DRAGON_VIDSRC_ENABLED"), "Playback providers"),
        "youtube": (("DRAGON_YOUTUBE_SYNC_ENABLED",), "YouTube synchronization"),
        "reading": (
            ("DRAGON_EXTERNAL_SYNC_ENABLED", "DRAGON_READING_TTS_ENABLED"),
            "Sync and text to speech",
        ),
        "ai": (("DRAGON_AI_ENABLED",), "AI workspace"),
    }
    keys, label = mapping.get(section.key, ((), "Local module"))
    if not keys:
        return [{"label": label, "enabled": True, "note": "Available locally"}]
    return [
        {
            "label": key.removeprefix("DRAGON_").replace("_", " ").title(),
            "enabled": bool(config.get(key)),
            "note": "Configured" if config.get(key) else "Disabled in runtime configuration",
        }
        for key in keys
    ]


def playback_manager():
    manager = current_app.extensions.get("dragon_magnet_playback_manager")
    if manager is None:
        manager = build_playback_manager(
            instance_path=current_app.instance_path,
            cache_limit_gb=current_app.config["DRAGON_PLAYBACK_CACHE_GB"],
            cache_ttl_hours=current_app.config["DRAGON_PLAYBACK_CACHE_TTL_HOURS"],
        )
        current_app.extensions["dragon_magnet_playback_manager"] = manager
    return manager


def _human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit in {"B", "KB"} else f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def build_section_state(section: SectionDefinition) -> dict[str, Any]:
    preferences = _request_preferences()["sections"][section.key]
    freshness = [get_freshness(domain) for domain in section.freshness_domains]
    last_operation = None
    if section.operation_domain:
        last_operation = db.session.scalar(
            db.select(Operation)
            .where(Operation.domain == section.operation_domain)
            .order_by(Operation.created_at.desc())
        )
    count = _table_count(section.table)
    states = {item["state"] for item in freshness}
    issues: list[str] = []
    status = "healthy"
    if last_operation and last_operation.status == "failed":
        status = "error"
        issues.append(last_operation.safe_error or "The latest operation failed.")
    elif states & {"malformed", "failed", "error"}:
        status = "error"
        issues.append("A local snapshot needs repair.")
    elif states & {"missing", "stale"}:
        status = "warning"
        issues.append("Data is missing or older than expected.")
    if count is None and section.table:
        status = "warning" if status == "healthy" else status
        issues.append("The module database table is not installed yet.")
    if not preferences["show_in_navigation"]:
        issues.append("Hidden from primary navigation by preference.")
    playback_cache = None
    if section.key == "movies":
        playback_cache = playback_manager().cache_status()
        playback_cache["used_label"] = _human_bytes(playback_cache["used_bytes"])
        playback_cache["limit_label"] = _human_bytes(playback_cache["limit_bytes"])
    return {
        "definition": section,
        "available": section.endpoint in current_app.view_functions,
        "preferences": preferences,
        "count": count,
        "status": status,
        "issues": issues,
        "freshness": freshness,
        "last_operation": last_operation,
        "capabilities": _capabilities(section),
        "playback_cache": playback_cache,
    }


def build_control_center() -> dict[str, Any]:
    sections = [build_section_state(section) for section in SECTIONS]
    return {
        "sections": sections,
        "healthy": sum(item["status"] == "healthy" for item in sections),
        "attention": sum(item["status"] != "healthy" for item in sections),
        "hidden": sum(not item["preferences"]["show_in_navigation"] for item in sections),
    }
