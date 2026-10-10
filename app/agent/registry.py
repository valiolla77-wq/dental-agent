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
        "جستجوی خدمات فعال دندانپزشکی بر اساس نام.",
        SearchDentalServicesInput,
        tools.search_dental_services,
    ),
    "find_doctors_for_service": ToolDefinition(
        "find_doctors_for_service",
        "read",
        "یافتن پزشکان فعال ارائه‌دهنده یک خدمت.",
        FindDoctorsForServiceInput,
        tools.find_doctors_for_service,
    ),
    "find_available_slots": ToolDefinition(
        "find_available_slots",
        "read",
        "دریافت زمان‌های واقعاً آزاد پزشک برای تاریخ مشخص.",
        FindAvailableSlotsInput,
        tools.find_available_slots,
    ),
    "get_patient_appointments": ToolDefinition(
        "get_patient_appointments",
        "read",
        "دریافت نوبت‌های یک بیمار.",
        GetPatientAppointmentsInput,
        tools.get_patient_appointments,
    ),
    "book_appointment": ToolDefinition(
        "book_appointment",
        "write",
        "ثبت نوبت پس از تأیید کاربر.",
        BookAppointmentInput,
        tools.book_appointment,
    ),
    "cancel_appointment": ToolDefinition(
        "cancel_appointment",
        "write",
        "لغو نوبت پس از تأیید کاربر.",
        CancelAppointmentInput,
        tools.cancel_appointment,
    ),
    "reschedule_appointment": ToolDefinition(
        "reschedule_appointment",
        "write",
        "جابه‌جایی نوبت پس از تأیید کاربر.",
        RescheduleAppointmentInput,
        tools.reschedule_appointment,
    ),
}


def get_llm_tool_schemas() -> list[dict[str, object]]:
    """Return provider-neutral function schemas for the allowlisted tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": definition.name,
                "description": definition.description,
                "parameters": definition.input_schema.model_json_schema(),
            },
        }
        for definition in TOOL_REGISTRY.values()
    ]


def get_tool_definition(name: str) -> ToolDefinition | None:
    """Return an allowlisted tool definition without exposing DB operations."""
    return TOOL_REGISTRY.get(name)
