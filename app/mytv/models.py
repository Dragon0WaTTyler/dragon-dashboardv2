from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.shared.time import utc_now


class TVPlaylist(db.Model):
    __tablename__ = "tv_playlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("tv_sources.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    github_path: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    source_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    source_sha: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    imported_sha: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    imported: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    channel_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    group_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sync_status: Mapped[str] = mapped_column(String(30), default="catalogued", nullable=False)
    sync_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    source: Mapped[TVSource | None] = relationship(back_populates="playlists")
    groups: Mapped[list[TVGroup]] = relationship(
        back_populates="playlist", cascade="all, delete-orphan", passive_deletes=True
    )
    channels: Mapped[list[TVChannel]] = relationship(
        back_populates="playlist", cascade="all, delete-orphan", passive_deletes=True
    )


class TVTheme(db.Model):
    __tablename__ = "tv_themes"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(240), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    channel_policy: Mapped[bool | None] = mapped_column(Boolean)
    channel_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    group_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    groups: Mapped[list[TVGroup]] = relationship(back_populates="theme", passive_deletes=True)


class TVThemePreference(db.Model):
    """Durable bouquet choices kept separately from disposable catalogue rows."""

    __tablename__ = "tv_theme_preferences"

    theme_key: Mapped[str] = mapped_column(String(240), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    channel_policy: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class TVGroup(db.Model):
    __tablename__ = "tv_groups"
    __table_args__ = (UniqueConstraint("playlist_id", "name", name="uq_tv_group_playlist_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    playlist_id: Mapped[int] = mapped_column(
        ForeignKey("tv_playlists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    theme_id: Mapped[int] = mapped_column(
        ForeignKey("tv_themes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    channel_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    playlist: Mapped[TVPlaylist] = relationship(back_populates="groups")
    theme: Mapped[TVTheme] = relationship(back_populates="groups")
    channels: Mapped[list[TVChannel]] = relationship(
        back_populates="group", cascade="all, delete-orphan", passive_deletes=True
    )


class TVChannel(db.Model):
    __tablename__ = "tv_channels"
    __table_args__ = (
        UniqueConstraint("playlist_id", "external_key", name="uq_tv_channel_external_key"),
        Index("ix_tv_channels_group_position", "group_id", "position"),
        Index("ix_tv_channels_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    playlist_id: Mapped[int] = mapped_column(
        ForeignKey("tv_playlists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("tv_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_key: Mapped[str] = mapped_column(String(64), nullable=False)
    preference_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(600), nullable=False)
    tvg_id: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    tvg_name: Mapped[str] = mapped_column(String(600), default="", nullable=False)
    logo_url: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    stream_url: Mapped[str] = mapped_column(Text, nullable=False)
    stream_kind: Mapped[str] = mapped_column(String(30), default="stream", nullable=False)
    enabled_override: Mapped[bool | None] = mapped_column(Boolean)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_seen_sync: Mapped[str] = mapped_column(String(40), nullable=False)

    playlist: Mapped[TVPlaylist] = relationship(back_populates="channels")
    group: Mapped[TVGroup] = relationship(back_populates="channels")


class TVChannelRepresentative(db.Model):
    """One current source row for every logical channel in the merged catalogue."""

    __tablename__ = "tv_channel_representatives"

    preference_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("tv_channels.id", ondelete="CASCADE"), unique=True, nullable=False
    )


class TVChannelHealth(db.Model):
    """Persistent reachability state for one logical channel."""

    __tablename__ = "tv_channel_health"

    preference_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False, index=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    source_fingerprint: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str] = mapped_column(String(240), default="", nullable=False)


class TVChannelPreference(db.Model):
    __tablename__ = "tv_channel_preferences"

    preference_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    theme_key: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(600), nullable=False)
    tvg_id: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    logo_url: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    enabled_override: Mapped[bool | None] = mapped_column(Boolean)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    last_watched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    watch_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    preferred_source_fingerprint: Mapped[str] = mapped_column(
        String(64), default="", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class TVProgramme(db.Model):
    """A small, disposable EPG cache keyed to a durable favorite channel ID."""

    __tablename__ = "tv_programmes"
    __table_args__ = (
        UniqueConstraint("tvg_id", "starts_at", "title", name="uq_tv_programme_slot"),
        Index("ix_tv_programmes_channel_window", "tvg_id", "starts_at", "ends_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tvg_id: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(600), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(600), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(500), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class TVEPGState(db.Model):
    """Persistent status for the favorite-only EPG refresh."""

    __tablename__ = "tv_epg_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    status: Mapped[str] = mapped_column(String(24), default="idle", nullable=False)
    message: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    last_error: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    matched_channels: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    programme_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class TVSource(db.Model):
    __tablename__ = "tv_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    locator: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    branch: Mapped[str] = mapped_column(String(160), default="main", nullable=False)
    file_pattern: Mapped[str] = mapped_column(String(500), default="*.m3u", nullable=False)
    local_path: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_refresh: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    refresh_interval_minutes: Mapped[int] = mapped_column(Integer, default=360, nullable=False)
    protected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="untested", nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    playlists: Mapped[list[TVPlaylist]] = relationship(back_populates="source")
