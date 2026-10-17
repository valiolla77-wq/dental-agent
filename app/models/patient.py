from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    national_id: Mapped[str] = mapped_column(
        String(10),
        unique=True,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(20))
    # Optional server-side link between a patient record and a user account.
    # NULL for legacy rows; set only by explicit staff-assisted linking.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
        unique=True,
        index=True,
    )