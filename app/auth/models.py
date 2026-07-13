from __future__ import annotations

from datetime import UTC, datetime

from flask_login import UserMixin
from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


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
