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
    "APPOINTMENT_DAILY_LIMIT": ErrorDefinition(
        "APPOINTMENT_DAILY_LIMIT", 409,
        "تعداد نوبت‌های فعال این بیمار در این روز به حد مجاز رسیده است.",
        "WARNING", False, "EXPLAIN_LIMIT_AND_STOP", "WARNING", "HIGH",
    ),
    "APPOINTMENT_WEEKLY_LIMIT": ErrorDefinition(
        "APPOINTMENT_WEEKLY_LIMIT", 409,
        "تعداد نوبت‌های فعال این بیمار در این هفته به حد مجاز رسیده است.",
        "WARNING", False, "EXPLAIN_LIMIT_AND_STOP", "WARNING", "HIGH",
    ),
    "APPOINTMENT_MONTHLY_LIMIT": ErrorDefinition(
        "APPOINTMENT_MONTHLY_LIMIT", 409,
        "تعداد نوبت‌های فعال این بیمار در این ماه به حد مجاز رسیده است.",
        "WARNING", False, "EXPLAIN_LIMIT_AND_STOP", "WARNING", "HIGH",
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
