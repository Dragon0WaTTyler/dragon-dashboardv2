from __future__ import annotations

import secrets
from urllib.parse import urljoin, urlparse

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_user, logout_user
from sqlalchemy import select

from app.auth.forms import LoginForm, LogoutForm
from app.auth.models import User
from app.extensions import db
from app.vault.google import GoogleOAuthClient, GoogleOAuthError
from app.vault.services import GoogleWorkspaceService

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _safe_next_url(target: str | None) -> bool:
    if not target:
        return False
    host = urlparse(request.host_url)
    destination = urlparse(urljoin(request.host_url, target))
    return destination.scheme in {"http", "https"} and host.netloc == destination.netloc


def _google_client() -> GoogleOAuthClient:
    injected = current_app.extensions.get("dragon_google_oauth_client")
    if injected is not None:
        return injected
    return GoogleOAuthClient(current_app.config)


def _google_redirect_uri() -> str:
    fallback = url_for("auth.google_callback", _external=True)
    return _google_client().redirect_uri(fallback)


def _google_personal_vault_enabled() -> bool:
    return bool(
        current_app.config.get("DRAGON_GOOGLE_OAUTH_ENABLED")
        and current_app.config.get("DRAGON_GOOGLE_PERSONAL_VAULT_LOGIN_ENABLED")
        and current_app.config.get("DRAGON_GOOGLE_PERSONAL_VAULT_SYNC_ENABLED")
    )


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("core.index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(select(User).where(User.username == form.username.data.strip()))
        if user and user.check_password(form.password.data) and user.is_active:
            target = request.args.get("next")
            session.clear()
            login_user(user, remember=form.remember.data, fresh=True)
            flash("Signed in.", "success")
            return redirect(target if _safe_next_url(target) else url_for("core.index"))
        flash("Username or password is incorrect.", "error")
    return render_template(
        "auth/login.html",
        form=form,
        google_personal_vault_enabled=_google_personal_vault_enabled(),
    )


@bp.get("/google")
def google_connect():
    if current_user.is_authenticated:
        return redirect(url_for("core.index"))
    if not _google_personal_vault_enabled():
        abort(404)
    state = secrets.token_urlsafe(32)
    session["google_oauth_state"] = state
    requested_next = request.args.get("next")
    if _safe_next_url(requested_next):
        session["google_oauth_next"] = requested_next
    try:
        authorization_url = _google_client().authorization_url(
            redirect_uri=_google_redirect_uri(), state=state
        )
        return redirect(authorization_url)
    except GoogleOAuthError as exc:
        flash(str(exc), "error")
        return redirect(url_for("auth.login"))


@bp.get("/google/callback")
def google_callback():
    if not _google_personal_vault_enabled():
        abort(404)
    expected_state = str(session.pop("google_oauth_state", ""))
    received_state = str(request.args.get("state") or "")
    if not expected_state or not secrets.compare_digest(expected_state, received_state):
        flash("Google connection could not be verified. Start again.", "error")
        return redirect(url_for("auth.login"))
    if request.args.get("error"):
        flash("Google connection was cancelled. Your Dragon data is unchanged.", "warning")
        return redirect(url_for("auth.login"))
    try:
        client = _google_client()
        tokens = client.exchange_code(
            code=str(request.args.get("code") or ""), redirect_uri=_google_redirect_uri()
        )
        identity = client.identity(access_token=str(tokens["access_token"]))
        user = GoogleWorkspaceService.connect(
            client=client,
            secret_key=str(current_app.config["SECRET_KEY"]),
            token_payload=tokens,
            identity_payload=identity,
        )
    except (GoogleOAuthError, ValueError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("auth.login"))
    target = str(session.pop("google_oauth_next", ""))
    session.clear()
    login_user(user, remember=True, fresh=True)
    flash("Your private Google Drive workspace is ready.", "success")
    return redirect(target if _safe_next_url(target) else url_for("core.index"))


@bp.post("/logout")
def logout():
    form = LogoutForm()
    if form.validate_on_submit():
        logout_user()
        session.clear()
        flash("Signed out.", "success")
    return redirect(url_for("auth.login"))
