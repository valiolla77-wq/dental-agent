"""Stable API error codes and their internal handling metadata."""

from dataclasses import dataclass
from typing import Any

from starlette.exceptions import HTTPException as StarletteHTTPException


@dataclass(frozen=True)
class ErrorDefinition:
    code: str
    status_code: int
    message: str
    severity: str
    retryable: bool
    agent_action: str
    logging_level: str
    security_sensitivity: str


# Internal catalog metadata is deliberately not serialized in API responses.
ERROR_CATALOG: dict[str, ErrorDefinition] = {
    "COMMON_VALIDATION_ERROR": ErrorDefinition(
        "COMMON_VALIDATION_ERROR", 422,
        "بعضی از اطلاعات واردشده معتبر نیست.", "INFO", False,
        "ASK_USER_TO_CORRECT_INPUT", "INFO", "LOW",
    ),
    "COMMON_NOT_FOUND": ErrorDefinition(
        "COMMON_NOT_FOUND", 404, "منبع درخواستی پیدا نشد.", "INFO", False,
        "STOP_AND_REPORT_NOT_FOUND", "INFO", "LOW",
    ),
    "COMMON_METHOD_NOT_ALLOWED": ErrorDefinition(
        "COMMON_METHOD_NOT_ALLOWED", 405,
        "این عملیات برای مسیر درخواستی مجاز نیست.", "WARNING", False,
        "STOP_AND_REPORT_UNSUPPORTED_ACTION", "WARNING", "LOW",
    ),
    "PATIENT_NOT_FOUND": ErrorDefinition(
        "PATIENT_NOT_FOUND", 404, "بیمار پیدا نشد.", "INFO", False,
        "STOP_AND_REPORT_NOT_FOUND", "INFO", "HIGH",
    ),
    "PATIENT_DUPLICATE_NATIONAL_ID": ErrorDefinition(
        "PATIENT_DUPLICATE_NATIONAL_ID", 409,
        "بیماری با این کد ملی قبلاً ثبت شده است.", "WARNING", False,
        "ASK_USER_TO_REVIEW_PATIENT", "WARNING", "HIGH",
    ),
    "PATIENT_DUPLICATE_PHONE": ErrorDefinition(
        "PATIENT_DUPLICATE_PHONE", 409,
        "این شماره تلفن قبلاً برای بیمار دیگری ثبت شده است.", "WARNING", False,
        "ASK_USER_TO_USE_ANOTHER_PHONE", "WARNING", "HIGH",
    ),
    "PATIENT_SELECTION_REQUIRED": ErrorDefinition(
        "PATIENT_SELECTION_REQUIRED", 409,
        "چند بیمار در این حساب ذخیره شده است؛ ابتدا بیمار موردنظر را انتخاب کنید.",
        "INFO", False, "ASK_USER_TO_SELECT_PATIENT", "INFO", "HIGH",
    ),
    "PATIENT_HAS_ACTIVE_APPOINTMENTS": ErrorDefinition(
        "PATIENT_HAS_ACTIVE_APPOINTMENTS", 409,
        "این بیمار نوبت فعال دارد؛ ابتدا نوبت‌های پیش‌رو را لغو کنید و سپس پرونده را حذف کنید.",
        "WARNING", False,
        "ASK_USER_TO_CANCEL_APPOINTMENTS_FIRST", "WARNING", "HIGH",
    ),
    "DOCTOR_NOT_FOUND": ErrorDefinition(
        "DOCTOR_NOT_FOUND", 404, "پزشک پیدا نشد.", "INFO", False,
        "STOP_AND_REPORT_NOT_FOUND", "INFO", "LOW",
    ),
    "DOCTOR_INACTIVE": ErrorDefinition(
        "DOCTOR_INACTIVE", 409,
        "این پزشک در حال حاضر فعال نیست.", "INFO", False,
        "OFFER_ANOTHER_DOCTOR", "INFO", "LOW",
    ),
    "DOCTOR_SCHEDULE_NOT_FOUND": ErrorDefinition(
        "DOCTOR_SCHEDULE_NOT_FOUND", 404,
        "برنامه پزشک پیدا نشد.", "INFO", False,
        "STOP_AND_REPORT_NOT_FOUND", "INFO", "LOW",
    ),
    "DENTAL_SERVICE_NOT_FOUND": ErrorDefinition(
        "DENTAL_SERVICE_NOT_FOUND", 404,
        "خدمت دندانپزشکی پیدا نشد.", "INFO", False,
        "STOP_AND_REPORT_NOT_FOUND", "INFO", "LOW",
    ),
    "DENTAL_SERVICE_IN_USE": ErrorDefinition(
        "DENTAL_SERVICE_IN_USE", 409,
        "این خدمت به یک نوبت ثبت‌شده متصل است و قابل حذف نیست.",
        "WARNING", False, "STOP_AND_REPORT_CONFLICT", "WARNING", "LOW",
    ),
    "APPOINTMENT_INVALID_DATE_OR_TIME": ErrorDefinition(
        "APPOINTMENT_INVALID_DATE_OR_TIME", 400,
        "تاریخ یا ساعت واردشده معتبر نیست.", "INFO", False,
        "ASK_USER_TO_CORRECT_INPUT", "INFO", "LOW",
    ),
    "APPOINTMENT_INVALID_DATE": ErrorDefinition(
        "APPOINTMENT_INVALID_DATE", 400,
        "تاریخ واردشده معتبر نیست.", "INFO", False,
        "ASK_USER_TO_CORRECT_INPUT", "INFO", "LOW",
    ),
    "APPOINTMENT_SLOT_IN_PAST": ErrorDefinition(
        "APPOINTMENT_SLOT_IN_PAST", 400,
        "زمان انتخاب‌شده گذشته است؛ لطفاً زمان آینده انتخاب کنید.", "INFO", False,
        "OFFER_AVAILABLE_SLOTS", "INFO", "LOW",
    ),
    "APPOINTMENT_NOT_FOUND": ErrorDefinition(
        "APPOINTMENT_NOT_FOUND", 404,
        "نوبت پیدا نشد.", "INFO", False,
        "STOP_AND_REPORT_NOT_FOUND", "INFO", "HIGH",
    ),
    "APPOINTMENT_ALREADY_CANCELLED": ErrorDefinition(
        "APPOINTMENT_ALREADY_CANCELLED", 409,
        "این نوبت قبلاً لغو شده است.", "INFO", False,
        "REPORT_ALREADY_CANCELLED", "INFO", "HIGH",
    ),
    "APPOINTMENT_NOT_CANCELLABLE": ErrorDefinition(
        "APPOINTMENT_NOT_CANCELLABLE", 409,
        "وضعیت فعلی این نوبت اجازه لغو آن را نمی‌دهد.", "WARNING", False,
        "STOP_AND_REPORT_CONFLICT", "WARNING", "HIGH",
    ),
    "APPOINTMENT_NOT_RESCHEDULABLE": ErrorDefinition(
        "APPOINTMENT_NOT_RESCHEDULABLE", 409,
        "وضعیت فعلی این نوبت اجازه جابه‌جایی آن را نمی‌دهد.", "WARNING", False,
        "STOP_AND_REPORT_CONFLICT", "WARNING", "HIGH",
    ),
    "APPOINTMENT_NOT_TODAY": ErrorDefinition(
        "APPOINTMENT_NOT_TODAY", 409,
        "پذیرش و تغییر وضعیت فقط برای نوبت‌های امروز ممکن است.", "WARNING", False,
        "STOP_AND_REPORT_CONFLICT", "WARNING", "MEDIUM",
    ),
    "APPOINTMENT_FLOW_INVALID": ErrorDefinition(
        "APPOINTMENT_FLOW_INVALID", 409,
        "وضعیت فعلی نوبت اجازه این مرحله را نمی‌دهد.", "WARNING", False,
        "STOP_AND_REPORT_CONFLICT", "WARNING", "MEDIUM",
    ),
    "PRESCRIPTION_INVALID": ErrorDefinition(
        "PRESCRIPTION_INVALID", 422,
        "اقلام نسخه معتبر نیست؛ حداقل یک دارو با نام و دوز لازم است.",
        "INFO", False, "ASK_USER_TO_CORRECT_INPUT", "INFO", "MEDIUM",
    ),
    "TREATMENT_PLAN_INVALID": ErrorDefinition(
        "TREATMENT_PLAN_INVALID", 422,
        "اقلام طرح درمان معتبر نیست.", "INFO", False,
        "ASK_USER_TO_CORRECT_INPUT", "INFO", "MEDIUM",
    ),
    "TREATMENT_PLAN_ITEM_NOT_FOUND": ErrorDefinition(
        "TREATMENT_PLAN_ITEM_NOT_FOUND", 404,
        "قلم طرح درمان پیدا نشد.", "INFO", False,
        "STOP_AND_REPORT_NOT_FOUND", "INFO", "LOW",
    ),
    "APPOINTMENT_DOCTOR_NOT_SCHEDULED": ErrorDefinition(
        "APPOINTMENT_DOCTOR_NOT_SCHEDULED", 409,
        "پزشک در این روز کاری ندارد.", "INFO", False,
        "OFFER_ANOTHER_DATE", "INFO", "LOW",
    ),
    "APPOINTMENT_SLOT_INVALID": ErrorDefinition(
        "APPOINTMENT_SLOT_INVALID", 400,
        "این ساعت یکی از زمان‌های معتبر نوبت‌دهی نیست.", "INFO", False,
        "OFFER_AVAILABLE_SLOTS", "INFO", "LOW",
    ),
    "APPOINTMENT_SLOT_BOOKED": ErrorDefinition(
        "APPOINTMENT_SLOT_BOOKED", 409,
        "این زمان قبلاً برای پزشک رزرو شده است.", "WARNING", False,
        "OFFER_AVAILABLE_SLOTS", "WARNING", "LOW",
    ),
    "APPOINTMENT_SERVICE_INACTIVE": ErrorDefinition(
        "APPOINTMENT_SERVICE_INACTIVE", 409,
        "این خدمت در حال حاضر قابل رزرو نیست.", "INFO", False,
        "OFFER_ANOTHER_SERVICE", "INFO", "LOW",
    ),
    "APPOINTMENT_DOCTOR_SERVICE_MISMATCH": ErrorDefinition(
        "APPOINTMENT_DOCTOR_SERVICE_MISMATCH", 409,
        "این پزشک خدمت انتخاب‌شده را ارائه نمی‌دهد.", "WARNING", False,
        "OFFER_DOCTORS_FOR_SERVICE", "WARNING", "LOW",
    ),
    "CLINICAL_ENTRY_INVALID": ErrorDefinition(
        "CLINICAL_ENTRY_INVALID", 422,
        "نوع یا عنوان یادداشت درمانی معتبر نیست.", "INFO", False,
        "ASK_USER_TO_CORRECT_INPUT", "INFO", "MEDIUM",
    ),
    "TOOTH_INVALID": ErrorDefinition(
        "TOOTH_INVALID", 422,
        "شماره دندان معتبر نیست؛ شماره‌گذاری FDI بین ۱۱ تا ۴۸ است.", "INFO", False,
        "ASK_USER_TO_CORRECT_INPUT", "INFO", "LOW",
    ),
    "TOOTH_STATUS_INVALID": ErrorDefinition(
        "TOOTH_STATUS_INVALID", 422,
        "وضعیت دندان معتبر نیست.", "INFO", False,
        "ASK_USER_TO_CORRECT_INPUT", "INFO", "LOW",
    ),
    "NOTIFICATION_NOT_FOUND": ErrorDefinition(
        "NOTIFICATION_NOT_FOUND", 404,
        "اعلان پیدا نشد یا به حساب شما تعلق ندارد.", "INFO", False,
        "STOP_AND_REPORT_NOT_FOUND", "INFO", "LOW",
    ),
    "VISIT_RATING_INVALID": ErrorDefinition(
        "VISIT_RATING_INVALID", 422,
        "امتیاز رضایت باید عددی بین ۱ تا ۵ باشد.", "INFO", False,
        "ASK_USER_TO_CORRECT_INPUT", "INFO", "LOW",
    ),
    "VISIT_RATING_ALREADY_SUBMITTED": ErrorDefinition(
        "VISIT_RATING_ALREADY_SUBMITTED", 409,
        "برای این نوبت قبلاً امتیاز ثبت شده است.", "INFO", False,
        "STOP_AND_REPORT_CONFLICT", "INFO", "LOW",
    ),
    "VISIT_NOT_RATEABLE": ErrorDefinition(
        "VISIT_NOT_RATEABLE", 409,
        "فقط نوبت‌های گذشته و لغو نشده قابل امتیازدهی هستند.", "INFO", False,
        "STOP_AND_REPORT_CONFLICT", "INFO", "LOW",
    ),
    "DATABASE_ERROR": ErrorDefinition(
        "DATABASE_ERROR", 500,
        "انجام درخواست به‌دلیل خطای داخلی ممکن نشد.", "ERROR", False,
        "RETRY_ONCE_THEN_HANDOFF", "ERROR", "MEDIUM",
    ),
    "INTERNAL_ERROR": ErrorDefinition(
        "INTERNAL_ERROR", 500,
        "خطای داخلی رخ داد. لطفاً بعداً دوباره تلاش کنید.", "ERROR", False,
        "HANDOFF_TO_HUMAN", "ERROR", "MEDIUM",
    ),
    "COMMON_UNAUTHORIZED": ErrorDefinition(
        "COMMON_UNAUTHORIZED", 401,
        "احراز هویت ناموفق یا توکن نامعتبر.", "INFO", False,
        "ASK_USER_TO_LOGIN", "INFO", "LOW",
    ),
    "COMMON_FORBIDDEN": ErrorDefinition(
        "COMMON_FORBIDDEN", 403,
        "دسترسی مجاز نیست.", "WARNING", False,
        "STOP_AND_REPORT_FORBIDDEN", "WARNING", "LOW",
    ),
    "COMMON_BAD_REQUEST": ErrorDefinition(
        "COMMON_BAD_REQUEST", 400,
        "درخواست معتبر نیست.", "INFO", False,
        "ASK_USER_TO_CORRECT_INPUT", "INFO", "LOW",
    ),
    "COMMON_CONFLICT": ErrorDefinition(
        "COMMON_CONFLICT", 409,
        "درخواست با وضعیت فعلی سیستم تضاد دارد.", "WARNING", False,
        "STOP_AND_REPORT_CONFLICT", "WARNING", "LOW",
    ),
    "PATIENT_ACCOUNT_NOT_LINKED": ErrorDefinition(
        "PATIENT_ACCOUNT_NOT_LINKED", 403,
        "حساب شما هنوز پرونده بیمار ندارد؛ لطفاً در فرم ثبت‌نام نام، کد ملی و شماره تلفن را وارد کنید.",
        "WARNING", False,
        "ASK_USER_TO_CONTACT_RECEPTION", "WARNING", "HIGH",
    ),
    "DOCTOR_ACCOUNT_NOT_LINKED": ErrorDefinition(
        "DOCTOR_ACCOUNT_NOT_LINKED", 403,
        "حساب پزشک شما هنوز به پرونده‌ای پیوست نشده است؛ لطفاً با مدیر تماس بگیرید.",
        "WARNING", False,
        "ASK_USER_TO_CONTACT_ADMIN", "WARNING", "LOW",
    ),
    "COMMON_TOO_MANY_REQUESTS": ErrorDefinition(
        "COMMON_TOO_MANY_REQUESTS", 429,
        "درخواست‌های شما بیش از حد مجاز است؛ لطفاً کمی بعد تلاش کنید.",
        "WARNING", True,
        "ASK_USER_TO_RETRY_LATER", "INFO", "LOW",
    ),
    "COMMON_SERVICE_UNAVAILABLE": ErrorDefinition(
        "COMMON_SERVICE_UNAVAILABLE", 503,
        "سرویس موردنظر در حال حاضر در دسترس نیست.", "ERROR", True,
        "HANDOFF_TO_HUMAN", "ERROR", "LOW",
    ),
    "AUTH_PORTAL_MISMATCH": ErrorDefinition(
        "AUTH_PORTAL_MISMATCH", 403,
        "این حساب برای ورود از این درگاه مجاز نیست؛ لطفاً از درگاه مربوط به نقش حساب خود استفاده کنید.",
        "WARNING", False,
        "ASK_USER_TO_USE_CORRECT_PORTAL", "WARNING", "HIGH",
    ),
    "USER_LAST_ADMIN_PROTECTED": ErrorDefinition(
        "USER_LAST_ADMIN_PROTECTED", 409,
        "حذف یا غیرفعال‌کردن تنها مدیر سیستم ممکن نیست؛ ابتدا یک مدیر دیگر تعریف کنید.",
        "WARNING", False,
        "STOP_AND_REPORT_CONFLICT", "WARNING", "HIGH",
    ),
    "USER_PERMISSIONS_NOT_EDITABLE": ErrorDefinition(
        "USER_PERMISSIONS_NOT_EDITABLE", 409,
        "تنظیم دسترسی برای این نقش ممکن نیست؛ فقط حساب‌های پذیرش و پزشک قابل تنظیم دارند.",
        "WARNING", False,
        "STOP_AND_REPORT_CONFLICT", "WARNING", "LOW",
    ),
    "AGENT_PROVIDER_NOT_CONFIGURED": ErrorDefinition(
        "AGENT_PROVIDER_NOT_CONFIGURED", 503,
        "اتصال به مدل زبانی پیکربندی نشده است؛ لطفاً بعداً تلاش کنید.",
        "ERROR", False,
        "HANDOFF_TO_HUMAN", "ERROR", "LOW",
    ),
    "AGENT_CONFIRMATION_INVALID": ErrorDefinition(
        "AGENT_CONFIRMATION_INVALID", 409,
        "این تأیید معتبر، منقضی یا متعلق به این نشست نیست؛ لطفاً عملیات را دوباره ثبت کنید.",
        "WARNING", False,
        "ASK_USER_TO_RESTART_ACTION", "WARNING", "HIGH",
    ),
    "AGENT_PROVIDER_RATE_LIMITED": ErrorDefinition(
        "AGENT_PROVIDER_RATE_LIMITED", 503,
        "سرویس هوش مصنوعی موقتاً شلوغ است؛ چند لحظه صبر کنید و دوباره تلاش کنید.",
        "WARNING", True,
        "RETRY_AFTER_DELAY", "WARNING", "LOW",
    ),
    "AGENT_PROVIDER_UNAVAILABLE": ErrorDefinition(
        "AGENT_PROVIDER_UNAVAILABLE", 503,
        "ارتباط با سرویس هوش مصنوعی برقرار نشد؛ لطفاً دوباره تلاش کنید.",
        "ERROR", True,
        "RETRY_AFTER_DELAY", "ERROR", "LOW",
    ),
}


class AppError(StarletteHTTPException):
    """An expected application error represented by a stable catalog code."""

    def __init__(self, code: str, details: dict[str, Any] | None = None):
        try:
            self.definition = ERROR_CATALOG[code]
        except KeyError as exc:
            raise ValueError(f"Unknown application error code: {code}") from exc

        self.code = code
        self.details = details or {}
        super().__init__(
            status_code=self.definition.status_code,
            detail=self.definition.message,
        )
