"""Allowlisted Agent Tool metadata and handlers."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel
from app.agent_tools import tools
from app.agent_tools.schemas import (
    BookAppointmentInput,
    CancelAppointmentInput,
    FindAvailableSlotsInput,
    FindDoctorsForServiceInput,
    FindNearestAppointmentsInput,
    GetPatientAppointmentsInput,
    RescheduleAppointmentInput,
    SearchDentalServicesInput,
)
from app.agent_tools.schemas import AgentToolResult


ToolHandler = Callable[..., Awaitable[AgentToolResult[Any]]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    operation: Literal["read", "write"]
    description: str
    input_schema: type[BaseModel]
    handler: ToolHandler


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "search_dental_services": ToolDefinition(
        "search_dental_services",
        "read",
        "فهرست یا جستجوی خدمات فعال کلینیک (نام، توضیح، شناسه). "
        "برای پیدا کردن شناسه خدمت یا تطبیق شکایت بیمار با خدمت موجود "
        "از چند کلیدواژه کوتاه استفاده کن؛ جمله کامل نفرست.",
        SearchDentalServicesInput,
        tools.search_dental_services,
    ),
    "find_doctors_for_service": ToolDefinition(
        "find_doctors_for_service",
        "read",
        "فهرست پزشکان فعالی که یک خدمت مشخص را ارائه می‌دهند. "
        "فقط وقتی لازم است که بیمار پزشک خاصی بخواهد یا باید بین "
        "پزشکان انتخاب شود.",
        FindDoctorsForServiceInput,
        tools.find_doctors_for_service,
    ),
    "find_available_slots": ToolDefinition(
        "find_available_slots",
        "read",
        "ساعت‌های واقعاً آزاد یک پزشک برای یک خدمت در یک روز مشخص "
        "(تاریخ جلالی). فقط وقتی تاریخ و پزشک مشخص‌اند؛ در غیر این صورت "
        "find_nearest_appointments را صدا بزن.",
        FindAvailableSlotsInput,
        tools.find_available_slots,
    ),
    "find_nearest_appointments": ToolDefinition(
        "find_nearest_appointments",
        "read",
        "نزدیک‌ترین نوبت‌های واقعاً آزاد یک خدمت مشخص در ۳۰ روز آینده "
        "(پزشک، خدمت، تاریخ جلالی، ساعت). ابتدا service_id را از "
        "search_dental_services بگیر؛ تاریخ لازم نیست.",
        FindNearestAppointmentsInput,
        tools.find_nearest_appointments,
    ),
    "get_patient_appointments": ToolDefinition(
        "get_patient_appointments",
        "read",
        "فهرست نوبت‌های بیمار مجاز با شناسه نوبت، وضعیت، تاریخ و ساعت. "
        "برای پیگیری، لغو یا جابه‌جایی لازم است. برای حساب بیمار، شناسه "
        "بیمار به‌صورت سرور-ساید تعیین می‌شود.",
        GetPatientAppointmentsInput,
        tools.get_patient_appointments,
    ),
    "book_appointment": ToolDefinition(
        "book_appointment",
        "write",
        "پیشنهاد ثبت نوبت. پس از بررسی آزاد بودن Slot فراخوانی کن؛ "
        "اجرا فقط پس از تأیید معتبر کاربر در رابط انجام می‌شود، نه با "
        "این فراخوانی.",
        BookAppointmentInput,
        tools.book_appointment,
    ),
    "cancel_appointment": ToolDefinition(
        "cancel_appointment",
        "write",
        "پیشنهاد لغو یک نوبت موجود (با شناسه نوبت از "
        "get_patient_appointments). اجرا فقط پس از تأیید معتبر کاربر.",
        CancelAppointmentInput,
        tools.cancel_appointment,
    ),
    "reschedule_appointment": ToolDefinition(
        "reschedule_appointment",
        "write",
        "پیشنهاد جابه‌جایی نوبت موجود به تاریخ و ساعت آزاد جدید. "
        "ابتدا آزاد بودن Slot را بررسی کن؛ اجرا فقط پس از تأیید معتبر "
        "کاربر.",
        RescheduleAppointmentInput,
        tools.reschedule_appointment,
    ),
}


# Fields the server fills in for patient-role actors. The model must neither
# see nor supply these; identity comes only from the authenticated session.
PATIENT_BOUND_FIELDS: dict[str, frozenset[str]] = {
    "book_appointment": frozenset(
        {"patient_id", "national_id", "full_name", "phone"}
    ),
    "get_patient_appointments": frozenset({"patient_id"}),
}


def _strip_fields(
    schema: dict[str, object], hidden: frozenset[str]
) -> dict[str, object]:
    """Remove hidden properties and required entries from a JSON schema."""
    stripped = dict(schema)
    properties = stripped.get("properties")
    if isinstance(properties, dict):
        stripped["properties"] = {
            key: value
            for key, value in properties.items()
            if key not in hidden
        }
    required = stripped.get("required")
    if isinstance(required, list):
        remaining = [key for key in required if key not in hidden]
        if remaining:
            stripped["required"] = remaining
        else:
            stripped.pop("required", None)
    return stripped


def get_llm_tool_schemas(
    patient_bound: bool = False,
) -> list[dict[str, object]]:
    """Return provider-neutral function schemas for the allowlisted tools.

    With ``patient_bound=True`` patient-identity fields are hidden from the
    model because the graph fills them from the authenticated patient account.
    Hiding fields is only a usability measure; server-side binding and
    ``authorize_tool_call`` remain the security boundary.
    """
    schemas: list[dict[str, object]] = []
    for definition in TOOL_REGISTRY.values():
        parameters = definition.input_schema.model_json_schema()
        hidden = PATIENT_BOUND_FIELDS.get(definition.name)
        if patient_bound and hidden:
            parameters = _strip_fields(parameters, hidden)
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": definition.name,
                    "description": definition.description,
                    "parameters": parameters,
                },
            }
        )
    return schemas


def get_tool_definition(name: str) -> ToolDefinition | None:
    """Return an allowlisted tool definition without exposing DB operations."""
    return TOOL_REGISTRY.get(name)
