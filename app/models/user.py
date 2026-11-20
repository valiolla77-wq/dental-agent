from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Audit fields: when the account was created and when it last logged in
    # successfully (naive UTC, like the rest of the codebase).
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Per-account permission overrides applied on top of the role matrix,
    # e.g. {"patient:create": "allow", "patient:delete": "deny"}.
    # Only meaningful for staff roles; admins and patients are never
    # affected by overrides (see app/auth/permissions.py).
    permission_overrides: Mapped[dict[str, str] | None] = mapped_column(
        JSON, nullable=True
    )

    def overrides_dict(self) -> dict[str, str]:
        """Return the stored overrides as a plain dict (never None)."""
        raw = self.permission_overrides
        if not isinstance(raw, dict):
            return {}
        return {
            str(key): str(value)
            for key, value in raw.items()
            if isinstance(key, str) and isinstance(value, str)
        }
