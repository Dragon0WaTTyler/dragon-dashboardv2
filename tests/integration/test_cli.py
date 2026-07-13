from sqlalchemy import select

from app.auth.models import User
from app.extensions import db


def test_admin_create_and_password_update(app):
    runner = app.test_cli_runner()
    created = runner.invoke(
        args=["admin", "create", "--username", "owner"],
        input="a-secure-local-password\na-secure-local-password\n",
    )
    assert created.exit_code == 0
    with app.app_context():
        user = db.session.scalar(select(User).where(User.username == "owner"))
        assert user is not None
        assert user.check_password("a-secure-local-password")

    updated = runner.invoke(
        args=["admin", "set-password", "--username", "owner"],
        input="another-secure-password\nanother-secure-password\n",
    )
    assert updated.exit_code == 0
    with app.app_context():
        user = db.session.scalar(select(User).where(User.username == "owner"))
        assert user.check_password("another-secure-password")


def test_admin_cli_rejects_short_password(app):
    runner = app.test_cli_runner()
    result = runner.invoke(
        args=["admin", "create", "--username", "owner"],
        input="too-short\ntoo-short\n",
    )
    assert result.exit_code != 0
    assert "at least 12 characters" in result.output
