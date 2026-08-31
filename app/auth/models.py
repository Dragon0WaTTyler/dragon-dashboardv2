from __future__ import annotations

from datetime import UTC, datetime

from flask_login import UserMixin
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.shared.ids import new_id


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    is_active_account: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    @property
    def is_active(self) -> bool:
        return self.is_active_account

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password, method="scrypt")

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class ExternalIdentity(db.Model):
    """A login identity owned by an external account provider, never by email alone."""

    __tablename__ = "external_identities"
    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_identity_provider_subject"),)

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id("identity")
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    display_name: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class PersonalWorkspace(db.Model):
    """A pointer to the owner-controlled remote vault, not a hosted data workspace."""

    __tablename__ = "personal_workspaces"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id("workspace")
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    storage_provider: Mapped[str] = mapped_column(
        String(40), default="google_drive", nullable=False
    )
    remote_locator: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    state: Mapped[str] = mapped_column(String(40), default="provisioning", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class WorkspaceConnection(db.Model):
    """Encrypted bootstrap credential for reaching a user's own remote vault."""

    __tablename__ = "workspace_connections"
    __table_args__ = (UniqueConstraint("workspace_id", "provider", name="uq_workspace_connection"),)

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id("connection")
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("personal_workspaces.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    credential_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
