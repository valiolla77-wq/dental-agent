"""Typed inputs and outputs for agent tool operations.

Every model-visible argument carries an explicit Persian description and, for
dates and times, the exact Jalali/24-hour format the services expect. The
patient identity fields on ``book_appointment`` remain in the base schema for
staff callers; for authenticated patients the graph hides them from the model
and injects the linked patient id server-side.
"""

import re
from typing import Any, Generic, TypeVar

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
    # Optional so a patient-role call can omit internal ids entirely. The
    # server resolves the target from the user's request and database facts.
    appointment_id: int | None = Field(
        default=None,
        gt=0,
        description=(
            "اختیاری؛ فقط برای کارکنان. برای حساب بیمار، نوبت با مشخصات "
            "درخواست کاربر و داده‌های سرور یکتا می‌شود."
        ),
    )


class RescheduleAppointmentInput(BaseModel):
    appointment_id: int | None = Field(
        default=None,
        gt=0,
        description=(
            "اختیاری؛ فقط برای کارکنان. برای حساب بیمار، نوبت فعلی با "
            "مشخصات درخواست کاربر و داده‌های سرور یکتا می‌شود."
        ),
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


class GetClinicAppointmentsReportInput(BaseModel):
    """Input for the staff-facing appointment workload summary."""

    window_days: int = Field(
        default=30,
        ge=1,
        le=90,
        description=(
            "بازهٔ آمار رو به جلو بر حسب روز؛ پیش‌فرض ۳۰ روز. برای "
            "«هفتهٔ پیش رو» مقدار ۷ بفرست."
        ),
    )


class DoctorAppointmentStatItem(BaseModel):
    doctor_id: int
    doctor_name: str
    scheduled_count: int


class ClinicAppointmentsReportToolData(BaseModel):
    """Real appointment aggregate for the requested forward window."""

    generated_at: str
    window_days: int
    today_appointments: int
    upcoming_scheduled: int
    upcoming_cancelled: int
    doctor_load: list[DoctorAppointmentStatItem]


class ClinicOverviewStatsInput(BaseModel):
    """Whole-clinic overview; admin-only tool with no parameters."""


class ClinicOverviewStatsToolData(BaseModel):
    generated_at: str
    patients_total: int
    patients_incomplete: int
    doctors_total: int
    services_total: int
    appointments_upcoming: int
    appointments_today: int
    cancellations_30d: int


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
    """Model-visible appointment facts; internal row ids are intentionally absent."""

    doctor_name: str
    service_name: str
    appointment_date: str
    appointment_time: str
    status: str


class BookAppointmentToolData(BaseModel):
    appointment_time: str
    status: str


class CancelAppointmentToolData(BaseModel):
    status: str


class RescheduleAppointmentToolData(BaseModel):
    appointment_time: str
    status: str


class SearchPatientsInput(BaseModel):
    """Front-desk style patient lookup; staff sessions only."""

    query: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "بخشی از نام، شماره تلفن یا کد ملی بیمار. برای «همهٔ» "
            "پرونده‌ها این مقدار را خالی بگذار؛ حداکثر ۱۰ نتیجه برمی‌گردد."
        ),
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=10,
        description="حداکثر تعداد نتیجه؛ حداکثر مقدار مجاز ۱۰ است.",
    )

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PatientSearchToolItem(BaseModel):
    """One patient row as the front desk may see it.

    The national id is intentionally masked; full digits are never handed to
    the model or read aloud in chat.
    """

    id: int
    full_name: str
    phone: str
    national_id_masked: str | None
    record_status: str


class PatientSummaryInput(BaseModel):
    """Single-patient card for the front desk; staff sessions only."""

    patient_id: int = Field(
        gt=0,
        description=(
            "شناسه بیمار از نتیجه search_patients یا get_doctor_day_plan."
        ),
    )


class PatientSummaryAppointmentItem(BaseModel):
    appointment_date: str
    appointment_time: str
    doctor_name: str
    service_name: str
    status: str


class PatientSummaryToolData(BaseModel):
    """Bounded patient overview: identity facts plus appointment counters."""

    patient_id: int
    full_name: str
    phone: str
    national_id_masked: str | None
    record_status: str
    is_account_holder: bool
    upcoming_count: int
    next_appointment: PatientSummaryAppointmentItem | None
    recent_appointments: list[PatientSummaryAppointmentItem]


class DoctorScheduleItem(BaseModel):
    """One weekly working block of one doctor."""

    doctor_id: int
    doctor_name: str
    specialty: str
    weekday: str
    start_time: str
    end_time: str
    slot_duration_minutes: int


class GetDoctorSchedulesInput(BaseModel):
    doctor_id: int | None = Field(
        default=None,
        gt=0,
        description=(
            "اختیاری؛ برای برنامه هفتگی یک پزشک مشخص. بدون این مقدار، "
            "برنامه همه پزشکان فعال برمی‌گردد."
        ),
    )


class DoctorSchedulesToolData(BaseModel):
    schedules: list[DoctorScheduleItem]


class GetDoctorDayPlanInput(BaseModel):
    """Staff day agenda for one doctor; doctor accounts are auto-scoped."""

    appointment_date: str | None = Field(
        default=None,
        max_length=20,
        description=(
            "تاریخ جلالی با قالب YYYY/MM/DD مثل 1405/08/15؛ خالی بگذاری "
            "یعنی امروز به وقت تهران."
        ),
    )
    doctor_id: int | None = Field(
        default=None,
        gt=0,
        description=(
            "اختیاری برای مدیر و پذیرش؛ حساب پزشک همیشه به پروندهٔ خودش "
            "محدود می‌شود و این مقدار نادیده گرفته می‌شود."
        ),
    )

    @field_validator("appointment_date")
    @classmethod
    def normalize_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _normalize_jalali_date(value)
        return normalized or None


class DayPlanAppointmentItem(BaseModel):
    """One row of a staff agenda; internal ids stay server-side only for staff."""

    appointment_id: int
    patient_name: str
    service_name: str
    appointment_time: str
    status: str
    reason: str | None


class DoctorDayPlanToolData(BaseModel):
    doctor_id: int
    doctor_name: str
    appointment_date: str
    weekday: str
    working_hours: str | None
    appointments: list[DayPlanAppointmentItem]


class FeedbackSummaryInput(BaseModel):
    """Admin-only feedback inbox snapshot; no parameters."""


class FeedbackItem(BaseModel):
    id: int
    category: str
    status: str
    created_at: str
    message_preview: str


class FeedbackSummaryToolData(BaseModel):
    total: int
    by_category: dict[str, int]
    by_status: dict[str, int]
    recent: list[FeedbackItem]


class MyProfileInput(BaseModel):
    """Self-service profile card; no parameters."""


class MyProfileRecordItem(BaseModel):
    """One patient record owned by the authenticated patient account.

    The national id is never included; the model only needs relation and
    record status to answer «پروفایل من چیه؟».
    """

    patient_id: int
    full_name: str
    phone: str
    relation: str
    record_status: str
    upcoming_count: int
    next_appointment: PatientSummaryAppointmentItem | None


class MyProfileToolData(BaseModel):
    """Self-service profile card for patient accounts."""

    records: list[MyProfileRecordItem]


class CreatePatientInput(BaseModel):
    """Front-desk registration of a new patient record; staff sessions only."""

    national_id: str = Field(
        min_length=1,
        max_length=20,
        description="کد ملی ۱۰ رقمی بیمار جدید؛ ارقام لاتین یا فارسی.",
    )
    full_name: str = Field(
        min_length=1,
        max_length=150,
        description="نام کامل بیمار جدید.",
    )
    phone: str = Field(
        min_length=1,
        max_length=20,
        description="شماره تلفن بیمار جدید؛ در سامانه یکتاست.",
    )

    @field_validator("full_name")
    @classmethod
    def reject_blank_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class CreatePatientToolData(BaseModel):
    """Result of a staff-registered patient record; id stays server-side."""

    full_name: str
    phone: str
    record_status: str


class UpdatePatientInput(BaseModel):
    """Front-desk edit of an existing record; at least one field must change."""

    patient_id: int = Field(
        gt=0,
        description="شناسه بیمار از نتیجه search_patients یا get_patient_summary.",
    )
    full_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=150,
        description="نام کامل جدید؛ خالی بگذاری یعنی بدون تغییر.",
    )
    phone: str | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        description="تلفن جدید؛ خالی بگذاری یعنی بدون تغییر.",
    )
    national_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        description="کد ملی جدید؛ فقط برای تکمیل پرونده‌های ناقص قدیمی.",
    )

    @field_validator("full_name")
    @classmethod
    def reject_blank_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized

    @model_validator(mode="after")
    def require_one_change(self):
        if (
            self.full_name is None
            and self.phone is None
            and self.national_id is None
        ):
            raise ValueError(
                "At least one of full_name, phone, or national_id is required"
            )
        return self


class UpdatePatientToolData(BaseModel):
    """Post-edit facts of the record; the row id stays server-side."""

    full_name: str
    phone: str
    national_id_masked: str | None
    record_status: str


class StaffDirectoryInput(BaseModel):
    """Administrator-only account overview; no parameters."""


class StaffDirectoryItem(BaseModel):
    """One staff account as the admin directory may see it."""

    user_id: int
    full_name: str
    role: str
    is_active: bool
    last_login_at: str | None


class StaffDirectoryToolData(BaseModel):
    """Administrator-only overview of user accounts."""

    total_accounts: int
    by_role: dict[str, int]
    active_accounts: int
    inactive_accounts: int
    recent_accounts: list[StaffDirectoryItem]


class AuditTrailInput(BaseModel):
    """Input for the admin audit-trail review tool."""

    limit: int = Field(
        default=10,
        ge=1,
        le=20,
        description="حداکثر تعداد رخداد اخیر؛ پیش‌فرض ۱۰ و حداکثر ۲۰.",
    )


class AuditTrailItem(BaseModel):
    """One append-only audit row, newest first, without internal actor ids."""

    action: str
    actor_phone: str | None
    target_label: str | None
    created_at: str
    detail: dict[str, object] | None


class AuditTrailToolData(BaseModel):
    """Recent sensitive actions recorded in the audit trail."""

    total_returned: int
    entries: list[AuditTrailItem]


class SubmitFeedbackInput(BaseModel):
    """In-chat error report or suggestion; open to every authenticated role."""

    category: str = Field(
        description="نوع گزارش: فقط «error» برای خطا یا «suggestion» برای پیشنهاد.",
    )
    message: str = Field(
        min_length=1,
        max_length=4000,
        description="متن گزارش یا پیشنهاد؛ همان متن کاربر را خلاصه و صادقانه انتقال بده.",
    )

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ("error", "suggestion"):
            raise ValueError("category must be 'error' or 'suggestion'")
        return normalized

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class SubmitFeedbackToolData(BaseModel):
    """Confirmation facts of a stored feedback row; the row id stays internal."""

    status: str


class AgentToolError(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


ResultData = TypeVar("ResultData")


class AgentToolResult(BaseModel, Generic[ResultData]):
    """Structured success or catalogued failure returned to an agent runtime.

    ``internal`` carries server-only values (for example the committed
    appointment row id needed for a success message). It is excluded from
    serialization, so it never reaches the model or an HTTP response.
    """

    ok: bool
    data: ResultData | None = None
    error: AgentToolError | None = None
    internal: dict[str, Any] = Field(default_factory=dict, exclude=True)
