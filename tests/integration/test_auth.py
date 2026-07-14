from sqlalchemy import select

from app.auth.models import User
from app.extensions import db
from tests.conftest import csrf_from, login


def test_password_is_hashed(app, admin_user):
    with app.app_context():
        user = db.session.scalar(select(User).where(User.username == "walid"))
        assert user.password_hash != "correct horse battery staple"
        assert user.password_hash.startswith("scrypt:")


def test_protected_pages_redirect_anonymous_user(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_login_clears_old_session_and_logout_requires_csrf(client, admin_user):
    with client.session_transaction() as session:
        session["untrusted_prelogin_value"] = "remove-me"

    response = login(client)
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert "untrusted_prelogin_value" not in session
        assert session.get("_fresh") is True

    rejected = client.post("/auth/logout")
    assert rejected.status_code == 400

    home = client.get("/")
    token = csrf_from(home)
    accepted = client.post("/auth/logout", data={"csrf_token": token})
    assert accepted.status_code == 302
    assert client.get("/").status_code == 302


def test_invalid_login_has_safe_message(client, admin_user):
    page = client.get("/auth/login")
    token = csrf_from(page)
    response = client.post(
        "/auth/login",
        data={"username": "walid", "password": "not-the-password", "csrf_token": token},
    )
    assert response.status_code == 200
    assert b"Username or password is incorrect" in response.data


def test_login_accepts_existing_short_password(client, app):
    with app.app_context():
        user = User(username="legacy-user", password_hash="")
        user.set_password("159654")
        db.session.add(user)
        db.session.commit()

    page = client.get("/auth/login")
    response = client.post(
        "/auth/login",
        data={
            "username": "legacy-user",
            "password": "159654",
            "csrf_token": csrf_from(page),
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_design_system_is_protected(authenticated_client):
    response = authenticated_client.get("/admin/design-system")
    assert response.status_code == 200
    assert b"Production primitives" in response.data
