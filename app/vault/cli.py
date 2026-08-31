from __future__ import annotations

import click
from flask import current_app
from flask.cli import with_appcontext


@click.command("vault-preflight")
@with_appcontext
def vault_preflight() -> None:
    """Report whether Google personal-workspace login is ready to activate."""

    config = current_app.config
    checks = (
        ("Google OAuth flag", bool(config.get("DRAGON_GOOGLE_OAUTH_ENABLED"))),
        (
            "Personal-workspace login flag",
            bool(config.get("DRAGON_GOOGLE_PERSONAL_VAULT_LOGIN_ENABLED")),
        ),
        (
            "Personal-workspace sync flag",
            bool(config.get("DRAGON_GOOGLE_PERSONAL_VAULT_SYNC_ENABLED")),
        ),
        ("Google OAuth client ID", bool(config.get("DRAGON_GOOGLE_OAUTH_CLIENT_ID"))),
        (
            "Google OAuth client secret",
            bool(config.get("DRAGON_GOOGLE_OAUTH_CLIENT_SECRET")),
        ),
        (
            "Google OAuth callback URL",
            bool(config.get("DRAGON_GOOGLE_OAUTH_REDIRECT_URI")),
        ),
    )
    for label, ready in checks:
        click.echo(f"{'OK' if ready else 'MISSING'}  {label}")
    if not all(ready for _, ready in checks):
        raise click.ClickException(
            "Google personal vault is not ready. Configure the missing private environment values."
        )
    click.echo("READY  Google personal vault can be activated on this installation.")
    click.echo(
        "Reminder: confirm the same callback URL is registered in Google Cloud before sign-in."
    )
