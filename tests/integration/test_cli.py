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


def test_vault_preflight_reports_missing_private_configuration_without_secrets(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["vault-preflight"])

    assert result.exit_code != 0
    assert "MISSING  Google OAuth client secret" in result.output
    assert "Google personal vault is not ready" in result.output


def test_vault_preflight_reports_ready_without_printing_credentials(app):
    app.config.update(
        DRAGON_GOOGLE_OAUTH_ENABLED=True,
        DRAGON_GOOGLE_PERSONAL_VAULT_LOGIN_ENABLED=True,
        DRAGON_GOOGLE_PERSONAL_VAULT_SYNC_ENABLED=True,
        DRAGON_GOOGLE_OAUTH_CLIENT_ID="client-id-not-for-output",
        DRAGON_GOOGLE_OAUTH_CLIENT_SECRET="client-secret-not-for-output",
        DRAGON_GOOGLE_OAUTH_REDIRECT_URI="https://dragon.example/auth/google/callback",
    )
    result = app.test_cli_runner().invoke(args=["vault-preflight"])

    assert result.exit_code == 0
    assert "READY  Google personal vault can be activated" in result.output
    assert "client-id-not-for-output" not in result.output
    assert "client-secret-not-for-output" not in result.output
