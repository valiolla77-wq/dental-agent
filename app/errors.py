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
        "حساب بیمار شما هنوز به پرونده‌ای پیوست نشده است؛ لطفاً با پذیرش تماس بگیرید.",
        "WARNING", False,
        "ASK_USER_TO_CONTACT_RECEPTION", "WARNING", "HIGH",
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
    "AGENT_PROVIDER_NOT_CONFIGURED": ErrorDefinition(
        "AGENT_PROVIDER_NOT_CONFIGURED", 503,
        "اتصال به مدل زبانی پیکربندی نشده است؛ لطفاً بعداً تلاش کنید.",
        "ERROR", False,
        "HANDOFF_TO_HUMAN", "ERROR", "LOW",
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
