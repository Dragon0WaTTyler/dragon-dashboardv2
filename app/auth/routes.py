from __future__ import annotations

from urllib.parse import urljoin, urlparse

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import select

from app.auth.forms import LoginForm, LogoutForm
from app.auth.models import User
from app.extensions import db

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _safe_next_url(target: str | None) -> bool:
    if not target:
        return False
    host = urlparse(request.host_url)
    destination = urlparse(urljoin(request.host_url, target))
    return destination.scheme in {"http", "https"} and host.netloc == destination.netloc


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
    return render_template("auth/login.html", form=form)


@bp.post("/logout")
def logout():
    form = LogoutForm()
    if form.validate_on_submit():
        logout_user()
        session.clear()
        flash("Signed out.", "success")
    return redirect(url_for("auth.login"))
