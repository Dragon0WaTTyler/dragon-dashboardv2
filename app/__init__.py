from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, redirect, url_for

from .db import close_db, init_db


def create_app(test_config: dict | None = None) -> Flask:
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
        DATABASE=str(Path(app.instance_path) / "mytv.sqlite3"),
        MYTV_GITHUB_OWNER=os.environ.get(
            "MYTV_GITHUB_OWNER", "mesbahikarim63-commits"
        ),
        MYTV_GITHUB_REPO=os.environ.get("MYTV_GITHUB_REPO", "hot-dodo"),
        MYTV_GITHUB_BRANCH=os.environ.get("MYTV_GITHUB_BRANCH", "main"),
        MYTV_IMPORT_LIMIT=int(os.environ.get("MYTV_IMPORT_LIMIT", "3")),
        MYTV_MAX_CHANNELS_PER_PLAYLIST=int(
            os.environ.get("MYTV_MAX_CHANNELS_PER_PLAYLIST", "0")
        ),
        MYTV_FFMPEG=os.environ.get("MYTV_FFMPEG", "ffmpeg"),
        MYTV_MAX_TRANSCODES=int(os.environ.get("MYTV_MAX_TRANSCODES", "2")),
        MYTV_HTTP_TIMEOUT=int(os.environ.get("MYTV_HTTP_TIMEOUT", "20")),
        MYTV_ALLOW_PRIVATE_STREAMS=os.environ.get("MYTV_ALLOW_PRIVATE_STREAMS", "0")
        == "1",
        TMDB_API_KEY=os.environ.get("TMDB_API_KEY", ""),
        TMDB_API_TOKEN=os.environ.get("TMDB_API_TOKEN", ""),
        TMDB_BASE_URL=os.environ.get("TMDB_BASE_URL", "https://api.themoviedb.org/3"),
        TMDB_IMAGE_BASE_URL=os.environ.get(
            "TMDB_IMAGE_BASE_URL", "https://image.tmdb.org/t/p/w500"
        ),
        MEDIA_SEARCH_LIMIT=int(os.environ.get("MEDIA_SEARCH_LIMIT", "20")),
        MEDIA_HTTP_TIMEOUT=int(os.environ.get("MEDIA_HTTP_TIMEOUT", "20")),
        MEDIA_RELEASE_PROVIDER=os.environ.get("MEDIA_RELEASE_PROVIDER", "jackett"),
        JACKETT_URL=os.environ.get("JACKETT_URL", "http://127.0.0.1:9117"),
        JACKETT_API_KEY=os.environ.get("JACKETT_API_KEY", ""),
        JACKETT_MIN_SEEDERS=int(os.environ.get("JACKETT_MIN_SEEDERS", "5")),
        JACKETT_RESULT_LIMIT=int(os.environ.get("JACKETT_RESULT_LIMIT", "50")),
        NOTION_TOKEN=os.environ.get("NOTION_TOKEN", ""),
        NOTION_DATABASE_ID=os.environ.get("NOTION_DATABASE_ID", ""),
        NOTION_DATA_SOURCE_ID=os.environ.get("NOTION_DATA_SOURCE_ID", ""),
        NOTION_VERSION=os.environ.get("NOTION_VERSION", "2025-09-03"),
        NOTION_PROP_TITLE=os.environ.get("NOTION_PROP_TITLE", "Title"),
        NOTION_PROP_TMDB_ID=os.environ.get("NOTION_PROP_TMDB_ID", "TMDB ID"),
        NOTION_PROP_TYPE=os.environ.get("NOTION_PROP_TYPE", "Type"),
        NOTION_PROP_YEAR=os.environ.get("NOTION_PROP_YEAR", "Year"),
        NOTION_PROP_POSTER=os.environ.get("NOTION_PROP_POSTER", "Poster"),
        NOTION_PROP_OVERVIEW=os.environ.get("NOTION_PROP_OVERVIEW", "Overview"),
        NOTION_PROP_MAGNET=os.environ.get("NOTION_PROP_MAGNET", "Magnet"),
        NOTION_PROP_RELEASE_TITLE=os.environ.get(
            "NOTION_PROP_RELEASE_TITLE", "Release Title"
        ),
        NOTION_PROP_WATCHED=os.environ.get("NOTION_PROP_WATCHED", "Watched"),
        NOTION_PROP_DATE_WATCHED=os.environ.get(
            "NOTION_PROP_DATE_WATCHED", "Date Watched"
        ),
        NOTION_PROP_SEASON=os.environ.get("NOTION_PROP_SEASON", "Season"),
        NOTION_PROP_EPISODE=os.environ.get("NOTION_PROP_EPISODE", "Episode"),
        MEDIA_PLAYER_MODE=os.environ.get("MEDIA_PLAYER_MODE", "webtorrent"),
        MEDIA_EXTERNAL_PLAYER_URL_TEMPLATE=os.environ.get(
            "MEDIA_EXTERNAL_PLAYER_URL_TEMPLATE", ""
        ),
        WEBTORRENT_CDN_URL=os.environ.get(
            "WEBTORRENT_CDN_URL",
            "https://cdn.jsdelivr.net/npm/webtorrent@3.0.16/dist/webtorrent.min.js",
        ),
        WEBTORRENT_SW_CDN_URL=os.environ.get(
            "WEBTORRENT_SW_CDN_URL",
            "https://cdn.jsdelivr.net/npm/webtorrent@3.0.16/dist/sw.min.js",
        ),
    )

    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    init_db(app)
    app.teardown_appcontext(close_db)

    from .mytv import bp as mytv_bp
    from .media import bp as media_bp

    app.register_blueprint(mytv_bp)
    app.register_blueprint(media_bp)

    @app.get("/")
    def index():
        return redirect(url_for("mytv.page"))

    return app
