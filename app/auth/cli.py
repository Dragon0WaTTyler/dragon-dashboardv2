from __future__ import annotations

import click
from flask.cli import AppGroup
from sqlalchemy import select

from app.auth.models import User
from app.extensions import db

admin_cli = AppGroup("admin", help="Manage the local Dragon administrator.")


def _validated_password(prompt: str = "Password") -> str:
    password = click.prompt(prompt, hide_input=True, confirmation_prompt=True)
    if len(password) < 12:
        raise click.ClickException("Password must contain at least 12 characters.")
    return password


@admin_cli.command("create")
@click.option("--username", prompt=True, help="Local administrator username.")
def create_admin(username: str) -> None:
    normalized = username.strip()
    if not normalized:
        raise click.ClickException("Username cannot be empty.")
    if db.session.scalar(select(User).where(User.username == normalized)):
        raise click.ClickException("That username already exists.")
    user = User(username=normalized, password_hash="")
    user.set_password(_validated_password())
    db.session.add(user)
    db.session.commit()
    click.echo(f"Created administrator {normalized!r}.")


@admin_cli.command("set-password")
@click.option("--username", prompt=True, help="Existing administrator username.")
def set_admin_password(username: str) -> None:
    normalized = username.strip()
    user = db.session.scalar(select(User).where(User.username == normalized))
    if user is None:
        raise click.ClickException("Administrator not found.")
    user.set_password(_validated_password("New password"))
    db.session.commit()
    click.echo(f"Updated password for {normalized!r}.")
