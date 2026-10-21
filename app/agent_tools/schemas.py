"""Typed inputs and outputs for agent tool operations.

Every model-visible argument carries an explicit Persian description and, for
dates and times, the exact Jalali/24-hour format the services expect. The
patient identity fields on ``book_appointment`` remain in the base schema for
staff callers; for authenticated patients the graph hides them from the model
and injects the linked patient id server-side.
"""

import re
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def _normalize_jalali_date(value: str) -> str:
    """Normalize digit/dash variants without hiding catalogued errors.

    Format and plausible-Jalali-year validation belongs to the service layer so
    callers receive ``APPOINTMENT_INVALID_DATE`` rather than a generic schema
    error. Keeping this conversion lenient also keeps the tool error contract
    stable.
    """
    normalized = value.strip().translate(_PERSIAN_DIGITS)
    return normalized.replace("-", "/").replace(".", "/")


def _normalize_clock(value: str) -> str:
    normalized = value.strip().translate(_PERSIAN_DIGITS)
    match = _CLOCK_RE.fullmatch(normalized)
    if match is None:
        return normalized
    hour = int(match.group(1))
    minute = int(match.group(2))
    return f"{hour:02d}:{minute:02d}"


class SearchDentalServicesInput(BaseModel):
    query: str | None = Field(
        default=None,
        max_length=150,
        description=(
            "چند کلیدواژه کوتاه فارسی مانند «پوسیدگی»، «درد دندان» یا "
            "«جرم‌گیری»؛ جمله کامل بیمار را وارد نکن. برای دیدن همه خدمات "
            "فعال، این مقدار را خالی بگذار."
        ),
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="حداکثر تعداد خدمات بازگشتی.",
    )

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class FindDoctorsForServiceInput(BaseModel):
    service_id: int = Field(
        gt=0,
        description="شناسه خدمت از نتیجه search_dental_services.",
    )


class FindAvailableSlotsInput(BaseModel):
    service_id: int = Field(
        gt=0,
        description="شناسه خدمت انتخاب‌شده از search_dental_services.",
    )
    doctor_id: int = Field(
        gt=0,
        description="شناسه پزشک از نتیجه find_doctors_for_service.",
    )
    appointment_date: str = Field(
        min_length=1,
        max_length=20,
        description="تاریخ جلالی با قالب YYYY/MM/DD، مثل 1405/08/15.",
    )

    @field_validator("appointment_date")
    @classmethod
    def normalize_date(cls, value: str) -> str:
        return _normalize_jalali_date(value)


class FindNearestAppointmentsInput(BaseModel):
    """Filters for an automatic 30-day forward search."""

    service_id: int = Field(
        gt=0,
        description=(
            "شناسه خدمتِ انتخاب‌شده از نتیجه search_dental_services؛ "
            "جست‌وجوی بدون خدمت مجاز نیست تا نوبت خدمت نامرتبط پیشنهاد نشود."
        ),
    )
    doctor_id: int | None = Field(
        default=None,
        gt=0,
        description="اختیاری؛ فقط وقتی بیمار پزشک مشخصی را خواسته است.",
    )
    days: int = Field(
        default=30,
        ge=1,
        le=60,
        description="بازه جست‌وجوی رو به جلو بر حسب روز؛ پیش‌فرض ۳۰ روز.",
    )
    limit: int = Field(
        default=3,
        ge=1,
        le=10,
        description="حداکثر تعداد نوبت پیشنهادی؛ پیش‌فرض ۳.",
    )


class GetPatientAppointmentsInput(BaseModel):
    patient_id: int = Field(
        gt=0,
        description=(
            "شناسه بیمار؛ برای حساب نقش patient به‌صورت سرور-ساید از "
            "حساب واردشده تعیین می‌شود."
        ),
    )


class CancelAppointmentInput(BaseModel):
    appointment_id: int = Field(
        gt=0,
        description="شناسه نوبت واقعی از نتیجه get_patient_appointments.",
    )


class RescheduleAppointmentInput(BaseModel):
    appointment_id: int = Field(
        gt=0,
        description="شناسه نوبت واقعی از نتیجه get_patient_appointments.",
    )
    appointment_date: str = Field(
        min_length=1,
        max_length=20,
        description="تاریخ جلالی جدید با قالب YYYY/MM/DD، مثل 1405/08/15.",
    )
    appointment_time: str = Field(
        min_length=1,
        max_length=10,
        description="ساعت جدید ۲۴ساعته با قالب HH:MM، مثل 09:30.",
    )

    @field_validator("appointment_date")
    @classmethod
    def normalize_date(cls, value: str) -> str:
        return _normalize_jalali_date(value)

    @field_validator("appointment_time")
    @classmethod
    def normalize_time(cls, value: str) -> str:
        return _normalize_clock(value)


class BookAppointmentInput(BaseModel):
    """Booking input: existing patient_id or all new/existing patient details."""

    doctor_id: int = Field(
        gt=0,
        description="شناسه پزشک از نتیجه find_doctors_for_service یا Tool نوبت‌ها.",
    )
    service_id: int = Field(
        gt=0,
        description="شناسه خدمت انتخاب‌شده از search_dental_services.",
    )
    appointment_date: str = Field(
        min_length=1,
        max_length=20,
        description="تاریخ جلالی با قالب YYYY/MM/DD، مثل 1405/08/15.",
    )
    appointment_time: str = Field(
        min_length=1,
        max_length=10,
        description="ساعت ۲۴ساعته با قالب HH:MM، مثل 09:30.",
    )
    patient_id: int | None = Field(
        default=None,
        gt=0,
        description=(
            "شناسه بیمار موجود؛ برای حساب نقش patient نیازی نیست و "
            "به‌صورت سرور-ساید تعیین می‌شود."
        ),
    )
    national_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=10,
        description="کد ملی؛ فقط برای کارکنان و بیمار جدید.",
    )
    full_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=150,
        description="نام کامل؛ فقط برای کارکنان و بیمار جدید.",
    )
    phone: str | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        description="تلفن؛ فقط برای کارکنان و بیمار جدید.",
    )
    reason: str | None = Field(
        default=None,
        max_length=500,
        description="دلیل مراجعه به زبان بیمار؛ اختیاری.",
    )

    @field_validator("appointment_date")
    @classmethod
    def normalize_date(cls, value: str) -> str:
        return _normalize_jalali_date(value)

    @field_validator("appointment_time")
    @classmethod
    def normalize_time(cls, value: str) -> str:
        return _normalize_clock(value)

    @field_validator("national_id", "full_name", "phone")
    @classmethod
    def reject_blank_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def validate_patient_input(self):
        has_patient_id = self.patient_id is not None
        patient_fields = (self.national_id, self.full_name, self.phone)
        has_any_patient_field = any(value is not None for value in patient_fields)
        has_all_patient_fields = all(value is not None for value in patient_fields)

        if has_patient_id == has_any_patient_field:
            raise ValueError(
                "Provide either patient_id or national_id, full_name, and phone"
            )
        if has_any_patient_field and not has_all_patient_fields:
            raise ValueError(
                "national_id, full_name, and phone must all be provided"
            )
        return self


class DentalServiceToolItem(BaseModel):
    id: int
    name: str
    description: str | None


class DoctorToolItem(BaseModel):
    id: int
    full_name: str
    specialty: str


class AvailableSlotsToolData(BaseModel):
    service_id: int
    doctor_id: int
    appointment_date: str
    available_slots: list[str]


class NearestAppointmentToolItem(BaseModel):
    doctor_id: int
    doctor_name: str
    service_id: int
    service_name: str
    appointment_date: str
    appointment_time: str


class NearestAppointmentsToolData(BaseModel):
    search_days: int
    appointments: list[NearestAppointmentToolItem]


class PatientAppointmentToolItem(BaseModel):
    appointment_id: int
    doctor_id: int
    service_id: int
    appointment_date: str
    appointment_time: str
    status: str


class BookAppointmentToolData(BaseModel):
    appointment_id: int
    patient_id: int
    doctor_id: int
    service_id: int
    appointment_time: str
    status: str


class CancelAppointmentToolData(BaseModel):
    appointment_id: int
    status: str


class RescheduleAppointmentToolData(BaseModel):
    appointment_id: int
    patient_id: int
    doctor_id: int
    service_id: int
    appointment_time: str
    status: str


class AgentToolError(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


ResultData = TypeVar("ResultData")


class AgentToolResult(BaseModel, Generic[ResultData]):
    """Structured success or catalogued failure returned to an agent runtime."""

    ok: bool
    data: ResultData | None = None
    error: AgentToolError | None = None
