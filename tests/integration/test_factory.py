from pathlib import Path

from app import create_app
from app.extensions import db


def test_factories_are_isolated(tmp_path: Path):
    first = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "first-test-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'first.db').as_posix()}",
        }
    )
    second = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "second-test-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'second.db').as_posix()}",
        }
    )
    assert first is not second
    assert first.config["SECRET_KEY"] != second.config["SECRET_KEY"]
    assert first.config["SQLALCHEMY_DATABASE_URI"] != second.config["SQLALCHEMY_DATABASE_URI"]
    for application in (first, second):
        with application.app_context():
            db.session.remove()
            db.engine.dispose()


def test_security_headers_and_request_ids(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Request-ID"].startswith("req_")
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert "img-src 'self' data: https:" in response.headers["Content-Security-Policy"]


def test_sqlite_connections_enable_wal_and_busy_timeout(app):
    with app.app_context():
        with db.engine.connect() as connection:
            journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar_one()
            busy_timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one()
            foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
    assert str(journal_mode).lower() == "wal"
    assert int(busy_timeout) == 30000
    assert int(foreign_keys) == 1
