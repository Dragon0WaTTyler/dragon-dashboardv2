from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask, current_app, g


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    github_path TEXT NOT NULL UNIQUE,
    source_url TEXT NOT NULL,
    sha TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    imported INTEGER NOT NULL DEFAULT 0 CHECK (imported IN (0, 1)),
    available INTEGER NOT NULL DEFAULT 1 CHECK (available IN (0, 1)),
    channel_count INTEGER NOT NULL DEFAULT 0,
    group_count INTEGER NOT NULL DEFAULT 0,
    sync_status TEXT NOT NULL DEFAULT 'catalogued',
    sync_error TEXT,
    last_synced_at TEXT,
    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS channel_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    channel_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE (playlist_id, name)
);

CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES channel_groups(id) ON DELETE CASCADE,
    external_key TEXT NOT NULL,
    name TEXT NOT NULL,
    tvg_id TEXT,
    tvg_name TEXT,
    logo_url TEXT,
    stream_url TEXT NOT NULL,
    stream_kind TEXT NOT NULL DEFAULT 'stream',
    enabled_override INTEGER CHECK (enabled_override IN (0, 1) OR enabled_override IS NULL),
    position INTEGER NOT NULL DEFAULT 0,
    last_seen_sync TEXT NOT NULL,
    UNIQUE (playlist_id, external_key)
);

CREATE INDEX IF NOT EXISTS idx_channels_group ON channels(group_id);
CREATE INDEX IF NOT EXISTS idx_channels_playlist ON channels(playlist_id);
CREATE INDEX IF NOT EXISTS idx_channels_name ON channels(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_groups_playlist ON channel_groups(playlist_id);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db_path = Path(current_app.config["DATABASE"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(db_path, timeout=30)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 30000")
    return g.db


def connect_db(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def close_db(_error=None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db(app: Flask) -> None:
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(app.config["DATABASE"])
    try:
        connection.executescript(SCHEMA)
        connection.commit()
    finally:
        connection.close()

