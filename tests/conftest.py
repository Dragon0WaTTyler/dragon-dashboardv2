from __future__ import annotations

import re
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from flask_migrate import upgrade
from werkzeug.serving import make_server

from app import create_app
from app.auth.models import User
from app.extensions import db

CSRF_PATTERN = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    args = dict(browser_type_launch_args)
    if sys.platform == "win32":
        candidates = (
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        )
        executable = next((path for path in candidates if path.exists()), None)
        if executable is not None:
            args["executable_path"] = str(executable)
    return args


@pytest.fixture
def app(tmp_path: Path):
    database_path = tmp_path / "test.sqlite3"
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key-for-dragon",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "WTF_CSRF_ENABLED": True,
            "SERVER_NAME": "localhost",
        }
    )
    with application.app_context():
        upgrade(directory=str(Path(__file__).parents[1] / "migrations"))
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_user(app) -> User:
    with app.app_context():
        user = User(username="walid", password_hash="")
        user.set_password("correct horse battery staple")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    with app.app_context():
        return db.session.get(User, user_id)


def csrf_from(response) -> str:
    match = CSRF_PATTERN.search(response.get_data(as_text=True))
    assert match is not None
    return match.group(1)


def login(client, username: str = "walid", password: str = "correct horse battery staple"):
    page = client.get("/auth/login")
    token = csrf_from(page)
    return client.post(
        "/auth/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


@pytest.fixture
def authenticated_client(client, admin_user):
    response = login(client)
    assert response.status_code == 302
    return client


@pytest.fixture
def live_app(app, admin_user) -> Iterator[str]:
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
