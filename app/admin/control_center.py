from __future__ import annotations

import json
import os
import re
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
    default_views: tuple[tuple[str, str], ...] = (("overview", "Overview"),)
    default_sorts: tuple[tuple[str, str], ...] = (("recent", "Recently added"),)


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
            FeatureDefinition("progress", "Watching progress", "Show progress on movie cards."),
            FeatureDefinition(
                "personal_score", "Personal score", "Show your score beside each title."
            ),
        ),
        (
            ("watching", "Watching"),
            ("library", "Library"),
            ("finished", "Finished"),
            ("wishlist", "Wishlist"),
        ),
        (
            ("recent", "Recently added"),
            ("last_watched", "Last watched"),
            ("rating", "Rating"),
            ("year", "Year"),
            ("title", "Title"),
        ),
    ),
    SectionDefinition(
        "mytv",
        "IPTV",
        "Live channel packages and local playback controls.",
        "mytv.index",
        "tv_channels",
        show_on_today=True,
        default_views=(("watch", "Watch"), ("favorites", "Favorites"), ("manage", "Manage")),
        default_sorts=(
            ("favorites", "Favorites first"),
            ("name", "Channel name"),
            ("recent", "Recently added"),
        ),
    ),
    SectionDefinition(
        "personal_tv",
        "My TV",
        "Personal television sessions programmed from your connected media.",
        "personal_tv.index",
        "personal_tv_sessions",
        default_views=(("program", "Program"), ("session", "Current session")),
        default_sorts=(("recent", "Most recent"),),
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
        (("watch_later", "Watch Later"), ("groups", "Groups"), ("favorites", "Favorites")),
        (("recent", "Recently added"), ("title", "Title")),
    ),
    SectionDefinition(
        "reading",
        "News",
        "Articles, reader mode, saved stories, and source monitoring.",
        "reading.index",
        "articles",
        ("reading",),
        "reading",
        True,
        (
            FeatureDefinition(
                "source_health", "Source health view", "Show feed health in the dedicated Sources view."
            ),
            FeatureDefinition(
                "reader_mode", "Reader mode by default", "Open stories inside Dragon first."
            ),
            FeatureDefinition("images", "Article images", "Show story images in lists and reader."),
            FeatureDefinition("source", "Source name", "Show the publication source."),
            FeatureDefinition(
                "publication_date", "Publication date", "Show when each story was published."
            ),
            FeatureDefinition(
                "mark_read_automatically",
                "Mark as reading automatically",
                "Move unread stories to Reading when they are opened.",
            ),
        ),
        (("today", "Today"), ("recent", "Recent"), ("saved", "Saved"), ("sources", "Sources")),
        (("recent", "Recently added"), ("title", "Title")),
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
        (
            ("reading", "Reading"),
            ("library", "Library"),
            ("finished", "Finished"),
            ("wishlist", "Wishlist"),
        ),
        (
            ("recent", "Recently read"),
            ("progress", "Progress"),
            ("rating", "Rating"),
            ("title", "Title"),
        ),
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
        (("today", "Today"), ("puzzles", "Puzzles"), ("games", "Games")),
        (("recent", "Recent activity"), ("rating", "Rating")),
    ),
    SectionDefinition(
        "german",
        "German",
        "Learning resources and vocabulary.",
        "german.index",
        "german_resources",
        default_views=(
            ("today", "Today"),
            ("vocabulary", "Vocabulary"),
            ("listening", "Listening"),
            ("review", "Review"),
        ),
        default_sorts=(("recent", "Recent activity"), ("title", "Title")),
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


@dataclass(frozen=True, slots=True)
class HomeBlockDefinition:
    key: str
    label: str
    description: str
    section_key: str
    default_enabled: bool = True
    default_limit: int = 5


HOME_BLOCKS: tuple[HomeBlockDefinition, ...] = (
    HomeBlockDefinition(
        "continue_watching", "Continue watching", "Pick up your active movie or series.", "movies"
    ),
    HomeBlockDefinition(
        "continue_reading", "Continue reading", "Return to the book currently in progress.", "books"
    ),
    HomeBlockDefinition(
        "favorite_iptv",
        "Favorite IPTV",
        "Keep live favorites close to the home screen.",
        "mytv",
        False,
    ),
    HomeBlockDefinition(
        "latest_articles", "Latest articles", "A fresh mix from your saved sources.", "reading"
    ),
    HomeBlockDefinition(
        "youtube_feed", "YouTube feed", "A rotating Watch Later selection.", "youtube"
    ),
    HomeBlockDefinition(
        "chess_training", "Chess training", "Your next puzzles and practice queue.", "chess"
    ),
    HomeBlockDefinition(
        "recommended_movie",
        "Recommended movie",
        "One deliberate pick from your watch queue.",
        "movies",
    ),
)
HOME_BLOCK_MAP = {block.key: block for block in HOME_BLOCKS}


class PreferenceStore:
    version = 3

    def __init__(self, root: str | Path):
        self.path = Path(root).resolve() / "control-center.json"

    @staticmethod
    def defaults() -> dict[str, Any]:
        return {
            "schema_version": PreferenceStore.version,
            "general": {
                "appearance": "system",
                "layout_density": "comfortable",
                "language": "en",
                "start_destination": "home",
                "remember_filters": True,
                "remember_tabs": True,
                "remember_scroll_position": False,
            },
            "home": {
                "layout": [
                    {
                        "section": block.key,
                        "enabled": block.default_enabled,
                        "position": index,
                        "item_limit": block.default_limit,
                    }
                    for index, block in enumerate(HOME_BLOCKS)
                ]
            },
            "sections": {
                section.key: {
                    "enabled": True,
                    "show_in_navigation": True,
                    "show_on_home": section.show_on_today,
                    "default_view": section.default_views[0][0],
                    "default_sort": section.default_sorts[0][0],
                    "hide_completed": False,
                    "favorites_first": False,
                    "features": {feature.key: feature.default for feature in section.features},
                    **(
                        {
                            "movie_preferences": {
                                "autoplay_next": True,
                                "automatic_resume": True,
                                "default_subtitle_language": "",
                                "preferred_audio_language": "auto",
                                "preferred_quality": "auto",
                                "preferred_source": "",
                                "preferred_region": "US",
                                "reduced_effects": False,
                                "ambient_level": "subtle",
                            }
                        }
                        if section.key == "movies"
                        else {}
                    ),
                    **(
                        {"retention_days": 30, "never_delete_saved": True}
                        if section.key == "reading"
                        else {}
                    ),
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
        general = raw.get("general")
        if isinstance(general, dict):
            allowed = {
                "appearance": {"system", "light", "dark"},
                "layout_density": {"compact", "comfortable"},
                "language": {"ar", "en", "fr"},
                "start_destination": {"home", "last_section"},
            }
            for key, values in allowed.items():
                if general.get(key) in values:
                    defaults["general"][key] = general[key]
            for key in ("remember_filters", "remember_tabs", "remember_scroll_position"):
                if isinstance(general.get(key), bool):
                    defaults["general"][key] = general[key]
        home = raw.get("home")
        if isinstance(home, dict) and isinstance(home.get("layout"), list):
            saved_blocks = {
                item.get("section"): item
                for item in home["layout"]
                if isinstance(item, dict) and item.get("section") in HOME_BLOCK_MAP
            }
            layout = []
            for index, block in enumerate(HOME_BLOCKS):
                saved = saved_blocks.get(block.key, {})
                layout.append(
                    {
                        "section": block.key,
                        "enabled": saved.get("enabled")
                        if isinstance(saved.get("enabled"), bool)
                        else block.default_enabled,
                        "position": saved.get("position")
                        if isinstance(saved.get("position"), int) and saved["position"] >= 0
                        else index,
                        "item_limit": saved.get("item_limit")
                        if saved.get("item_limit") in {5, 10, 20}
                        else block.default_limit,
                    }
                )
            defaults["home"]["layout"] = sorted(layout, key=lambda item: item["position"])
        for section in SECTIONS:
            saved = raw["sections"].get(section.key)
            if not isinstance(saved, dict):
                continue
            target = defaults["sections"][section.key]
            for key in (
                "enabled",
                "show_in_navigation",
                "show_on_home",
                "hide_completed",
                "favorites_first",
            ):
                if isinstance(saved.get(key), bool):
                    target[key] = saved[key]
            # Version 1 stored this setting under its old screen name.
            if isinstance(saved.get("show_on_today"), bool):
                target["show_on_home"] = saved["show_on_today"]
            for key, allowed in (
                ("default_view", dict(section.default_views)),
                ("default_sort", dict(section.default_sorts)),
            ):
                if saved.get(key) in allowed:
                    target[key] = saved[key]
            features = saved.get("features")
            if isinstance(features, dict):
                for feature in section.features:
                    if isinstance(features.get(feature.key), bool):
                        target["features"][feature.key] = features[feature.key]
            if section.key == "reading":
                if saved.get("retention_days") in {7, 30, 90}:
                    target["retention_days"] = saved["retention_days"]
                if isinstance(saved.get("never_delete_saved"), bool):
                    target["never_delete_saved"] = saved["never_delete_saved"]
            if section.key == "movies":
                movie_preferences = saved.get("movie_preferences")
                if isinstance(movie_preferences, dict):
                    target_preferences = target["movie_preferences"]
                    for key in (
                        "autoplay_next",
                        "automatic_resume",
                        "reduced_effects",
                    ):
                        if isinstance(movie_preferences.get(key), bool):
                            target_preferences[key] = movie_preferences[key]
                    language = str(movie_preferences.get("default_subtitle_language") or "").lower()
                    if not language or re.fullmatch(r"[a-z]{2,3}", language):
                        target_preferences["default_subtitle_language"] = language
                    audio_language = str(
                        movie_preferences.get("preferred_audio_language") or "auto"
                    ).lower()
                    if audio_language == "auto" or audio_language == "original" or re.fullmatch(
                        r"[a-z]{2,3}", audio_language
                    ):
                        target_preferences["preferred_audio_language"] = audio_language
                    quality = str(movie_preferences.get("preferred_quality") or "auto").lower()
                    if quality in {"auto", "best", "1080p", "720p", "480p"}:
                        target_preferences["preferred_quality"] = quality
                    source = str(movie_preferences.get("preferred_source") or "").lower()
                    if not source or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", source):
                        target_preferences["preferred_source"] = source
                    region = str(movie_preferences.get("preferred_region") or "").upper()
                    if re.fullmatch(r"[A-Z]{2}", region):
                        target_preferences["preferred_region"] = region
                    if movie_preferences.get("ambient_level") in {
                        "off",
                        "subtle",
                        "normal",
                        "vivid",
                    }:
                        target_preferences["ambient_level"] = movie_preferences["ambient_level"]
        return defaults

    def _write(self, payload: dict[str, Any]) -> dict[str, Any]:
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

    def update(self, section_key: str, values: dict[str, Any]) -> dict[str, Any]:
        section = SECTION_MAP.get(section_key)
        if section is None:
            raise ValueError("Unknown section.")
        payload = self.read()
        target = payload["sections"][section.key]
        target["enabled"] = bool(values.get("enabled"))
        target["show_in_navigation"] = bool(values.get("show_in_navigation"))
        target["show_on_home"] = (
            bool(values.get("show_on_home")) if section.show_on_today else False
        )
        target["default_view"] = (
            values.get("default_view")
            if values.get("default_view") in dict(section.default_views)
            else section.default_views[0][0]
        )
        target["default_sort"] = (
            values.get("default_sort")
            if values.get("default_sort") in dict(section.default_sorts)
            else section.default_sorts[0][0]
        )
        target["hide_completed"] = bool(values.get("hide_completed"))
        target["favorites_first"] = bool(values.get("favorites_first"))
        target["features"] = {
            feature.key: bool(values.get(f"feature_{feature.key}")) for feature in section.features
        }
        if section.key == "reading":
            retention = str(values.get("retention_days") or "30")
            target["retention_days"] = int(retention) if retention in {"7", "30", "90"} else 30
            target["never_delete_saved"] = bool(values.get("never_delete_saved"))
        if section.key == "movies":
            movie_preferences = target["movie_preferences"]
            for key in (
                "autoplay_next",
                "automatic_resume",
                "reduced_effects",
            ):
                movie_preferences[key] = bool(values.get(key))
            language = str(values.get("default_subtitle_language") or "").strip().lower()
            movie_preferences["default_subtitle_language"] = (
                language if not language or re.fullmatch(r"[a-z]{2,3}", language) else ""
            )
            audio_language = str(values.get("preferred_audio_language") or "auto").strip().lower()
            movie_preferences["preferred_audio_language"] = (
                audio_language
                if audio_language in {"auto", "original"}
                or re.fullmatch(r"[a-z]{2,3}", audio_language)
                else "auto"
            )
            quality = str(values.get("preferred_quality") or "auto").strip().lower()
            movie_preferences["preferred_quality"] = (
                quality if quality in {"auto", "best", "1080p", "720p", "480p"} else "auto"
            )
            source = str(values.get("preferred_source") or "").strip().lower()
            movie_preferences["preferred_source"] = (
                source
                if not source or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", source)
                else ""
            )
            region = str(values.get("preferred_region") or "US").strip().upper()
            movie_preferences["preferred_region"] = (
                region if re.fullmatch(r"[A-Z]{2}", region) else "US"
            )
            ambient_level = str(values.get("ambient_level") or "subtle")
            movie_preferences["ambient_level"] = (
                ambient_level
                if ambient_level in {"off", "subtle", "normal", "vivid"}
                else "subtle"
            )
        return self._write(payload)

    def set_movie_preferences(self, values: dict[str, Any]) -> dict[str, Any]:
        """Apply an already-validated portable Movies preference payload."""

        payload = self.read()
        target = payload["sections"]["movies"]["movie_preferences"]
        for key in ("autoplay_next", "automatic_resume", "reduced_effects"):
            target[key] = bool(values[key])
        target["default_subtitle_language"] = str(values["default_subtitle_language"])
        target["preferred_audio_language"] = str(values.get("preferred_audio_language") or "auto")
        target["preferred_quality"] = str(values.get("preferred_quality") or "auto")
        target["preferred_source"] = str(values["preferred_source"])
        target["preferred_region"] = str(values["preferred_region"])
        target["ambient_level"] = str(values["ambient_level"])
        return self._write(payload)

    def update_general(self, values: dict[str, Any]) -> dict[str, Any]:
        payload = self.read()
        target = payload["general"]
        for key, allowed in {
            "appearance": {"system", "light", "dark"},
            "layout_density": {"compact", "comfortable"},
            "language": {"ar", "en", "fr"},
            "start_destination": {"home", "last_section"},
        }.items():
            if values.get(key) in allowed:
                target[key] = values[key]
        for key in ("remember_filters", "remember_tabs", "remember_scroll_position"):
            target[key] = bool(values.get(key))
        return self._write(payload)

    def update_home(self, values: dict[str, Any]) -> dict[str, Any]:
        payload = self.read()
        ordered_keys = [
            key for key in str(values.get("layout_order") or "").split(",") if key in HOME_BLOCK_MAP
        ]
        ordered_keys.extend(key for key in HOME_BLOCK_MAP if key not in ordered_keys)
        payload["home"]["layout"] = [
            {
                "section": key,
                "enabled": bool(values.get(f"home_{key}_enabled")),
                "position": index,
                "item_limit": int(values.get(f"home_{key}_limit"))
                if str(values.get(f"home_{key}_limit")) in {"5", "10", "20"}
                else HOME_BLOCK_MAP[key].default_limit,
            }
            for index, key in enumerate(ordered_keys)
        ]
        return self._write(payload)

    def reset_section(self, section_key: str) -> dict[str, Any]:
        if section_key not in SECTION_MAP:
            raise ValueError("Unknown section.")
        payload = self.read()
        payload["sections"][section_key] = self.defaults()["sections"][section_key]
        return self._write(payload)


def preference_store() -> PreferenceStore:
    root = current_app.config.get("DRAGON_CONTROL_CENTER_ROOT", current_app.instance_path)
    return PreferenceStore(root)


def section_visible(section_key: str) -> bool:
    section = _request_preferences()["sections"].get(section_key, {})
    return bool(section.get("enabled", True) and section.get("show_in_navigation", True))


def feature_enabled(section_key: str, feature_key: str) -> bool:
    section = _request_preferences()["sections"].get(section_key, {})
    if feature_key == "today":
        return bool(section.get("enabled", True) and section.get("show_on_home", False))
    return bool(section.get("enabled", True) and section.get("features", {}).get(feature_key, True))


def home_layout() -> list[dict[str, Any]]:
    preferences = _request_preferences()
    sections = preferences["sections"]
    result = []
    for item in preferences["home"]["layout"]:
        block = HOME_BLOCK_MAP[item["section"]]
        result.append(
            {
                **item,
                "definition": block,
                "visible": bool(
                    item["enabled"]
                    and sections[block.section_key]["enabled"]
                    and sections[block.section_key]["show_on_home"]
                ),
            }
        )
    return result


def home_block_visible(block_key: str) -> bool:
    return any(item["section"] == block_key and item["visible"] for item in home_layout())


def home_block_position(block_key: str) -> int:
    for item in home_layout():
        if item["section"] == block_key:
            return int(item["position"])
    return len(HOME_BLOCKS)


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
    if not preferences["enabled"]:
        issues.append("Disabled by preference.")
    elif not preferences["show_in_navigation"]:
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
        "default_view_label": dict(section.default_views).get(
            preferences["default_view"], preferences["default_view"]
        ),
        "default_sort_label": dict(section.default_sorts).get(
            preferences["default_sort"], preferences["default_sort"]
        ),
    }


def build_control_center() -> dict[str, Any]:
    sections = [build_section_state(section) for section in SECTIONS]
    return {
        "sections": sections,
        "healthy": sum(item["status"] == "healthy" for item in sections),
        "attention": sum(item["status"] != "healthy" for item in sections),
        "hidden": sum(not item["preferences"]["show_in_navigation"] for item in sections),
        "disabled": sum(not item["preferences"]["enabled"] for item in sections),
    }
