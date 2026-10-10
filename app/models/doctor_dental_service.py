from sqlalchemy import Column, ForeignKey, Integer, Table, UniqueConstraint

from app.models.base import Base


doctor_dental_services = Table(
    "doctor_dental_services",
    Base.metadata,
    Column("doctor_id", Integer, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False),
    Column(
        "dental_service_id",
        Integer,
        ForeignKey("dental_services.id", ondelete="CASCADE"),
        nullable=False,
    ),
    UniqueConstraint(
        "doctor_id",
        "dental_service_id",
        name="uq_doctor_dental_service",
    ),
)
