import sqlite3

from flask import g, has_request_context
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_sqlalchemy.session import Session
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


CENTRAL_TABLES = frozenset(
    {
        "users",
        "external_identities",
        "personal_workspaces",
        "workspace_connections",
        "migration_runs",
    }
)


class WorkspaceRoutingSession(Session):
    """Route personal models to the current user's disposable workspace cache."""

    def get_bind(self, mapper=None, clause=None, bind=None, **kwargs):
        if bind is None and mapper is not None and has_request_context():
            workspace_engine = getattr(g, "dragon_workspace_engine", None)
            table = getattr(inspect(mapper), "local_table", None)
            if (
                workspace_engine is not None
                and table is not None
                and table.name not in CENTRAL_TABLES
            ):
                return workspace_engine
        return super().get_bind(mapper=mapper, clause=clause, bind=bind, **kwargs)


@event.listens_for(Engine, "connect")
def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA busy_timeout = 30000")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
    finally:
        cursor.close()


db = SQLAlchemy(
    model_class=Base,
    engine_options={"connect_args": {"timeout": 30}},
    session_options={"class_": WorkspaceRoutingSession},
)
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
