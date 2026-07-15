from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

from flask import Flask

from app.admin import bp as admin_bp
from app.ai import bp as ai_bp
from app.api.v1 import bp as api_v1_bp
from app.auth import bp as auth_bp
from app.auth.cli import admin_cli
from app.auth.forms import LogoutForm
from app.auth.models import User
from app.books import bp as books_bp
from app.chess import bp as chess_bp
from app.config import Settings
from app.core import bp as core_bp
from app.errors import register_error_handlers
from app.extensions import csrf, db, login_manager, migrate
from app.german import bp as german_bp
from app.history import bp as history_bp
from app.logging_config import configure_logging
from app.middleware import install_request_middleware
from app.migration import migration_cli
from app.movies import bp as movies_bp
from app.playback import bp as playback_bp
from app.reading import bp as reading_bp
from app.reading.providers import ArticleExtractor
from app.youtube import bp as youtube_bp


def create_app(config_override: Mapping[str, Any] | None = None) -> Flask:
    configure_logging()
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    settings = Settings.load(app.instance_path, config_override)
    app.config.from_mapping(settings.flask_mapping(config_override))
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=14)
    app.extensions["dragon_settings"] = settings
    if not app.config.get("TESTING"):
        app.extensions["dragon_article_extractor"] = ArticleExtractor()

    install_request_middleware(app)
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Sign in to open your workspace."
    login_manager.login_message_category = "warning"
    login_manager.session_protection = "strong"

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        if not user_id.isdigit():
            return None
        return db.session.get(User, int(user_id))

    @app.context_processor
    def shared_template_context() -> dict[str, Any]:
        return {
            "logout_form": LogoutForm(),
            "feature_flags": settings.safe_summary(),
        }

    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(movies_bp)
    app.register_blueprint(playback_bp)
    app.register_blueprint(youtube_bp)
    app.register_blueprint(reading_bp)
    app.register_blueprint(books_bp)
    app.register_blueprint(chess_bp)
    app.register_blueprint(german_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(api_v1_bp)
    app.cli.add_command(admin_cli)
    app.cli.add_command(migration_cli)

    register_error_handlers(app)
    return app


__all__ = ["create_app"]
