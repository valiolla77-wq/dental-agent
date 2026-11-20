from sqlalchemy import Boolean, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Nullable only for legacy rows created before national id became
    # mandatory. Every current write path (staff, self-registration, booking)
    # requires and validates a 10-digit national id.
    national_id: Mapped[str | None] = mapped_column(
        String(10),
        unique=True,
        index=True,
        nullable=True,
    )
    full_name: Mapped[str] = mapped_column(String(150))
    # One phone number belongs to exactly one patient record. The account
    # holder and every family member therefore have distinct patient phones.
    phone: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        index=True,
    )
    # A patient account may own several patient records (the account holder
    # plus family members). The link is therefore intentionally non-unique;
    # authorization always resolves the complete owned set server-side.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    # Marks the account holder's own record within a multi-patient account.
    # At most one record per account can carry this flag.
    is_account_holder: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
        index=True,
    )
    # ``incomplete``: legacy record missing mandatory fields.
    # ``complete``: mandatory record fields are present. Derived on write;
    # never client-set.
    record_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="complete",
        server_default="complete",
        index=True,
    )

    __table_args__ = (
        # SQLite partial unique index: one account-holder record per account,
        # while any number of family records may share the same user_id.
        Index(
            "uq_patients_account_holder",
            "user_id",
            unique=True,
            sqlite_where=text("is_account_holder = 1"),
        ),
    )
