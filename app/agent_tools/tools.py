"""Agent-facing adapters that delegate operations to application services."""

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_tools.schemas import (
    AgentToolError,
    AgentToolResult,
    AvailableSlotsToolData,
    BookAppointmentInput,
    BookAppointmentToolData,
    CancelAppointmentInput,
    CancelAppointmentToolData,
    DentalServiceToolItem,
    DoctorToolItem,
    FindAvailableSlotsInput,
    FindDoctorsForServiceInput,
    FindNearestAppointmentsInput,
    GetPatientAppointmentsInput,
    NearestAppointmentToolItem,
    NearestAppointmentsToolData,
    PatientAppointmentToolItem,
    RescheduleAppointmentInput,
    RescheduleAppointmentToolData,
    SearchDentalServicesInput,
)
from app.errors import AppError, ERROR_CATALOG
from app.models.appointment import Appointment
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.services import appointment_service, booking_service, dental_service_service
from app.utils.date_utils import gregorian_to_jalali


logger = logging.getLogger("dental_agent.agent_tools")
ToolData = TypeVar("ToolData")


def _catalog_error(code: str) -> AgentToolError:
    definition = ERROR_CATALOG[code]
    return AgentToolError(
        code=definition.code,
        message=definition.message,
        # Tool errors deliberately omit exception details and rejected values.
        details={},
    )


async def _execute_tool(
    tool_name: str,
    operation: Callable[[], Awaitable[ToolData]],
) -> AgentToolResult[ToolData]:
    tool_call_id = str(uuid4())
    logger.info(
        "Agent tool started",
        extra={"tool_name": tool_name, "tool_call_id": tool_call_id},
    )
    try:
        data = await operation()
    except ValidationError:
        error = _catalog_error("COMMON_VALIDATION_ERROR")
        logger.info(
            "Agent tool rejected invalid input",
            extra={
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "error_code": error.code,
            },
        )
        return AgentToolResult[ToolData](ok=False, error=error)
    except AppError as exc:
        error = _catalog_error(exc.code)
        definition = ERROR_CATALOG[exc.code]
        log_method = getattr(logger, definition.logging_level.lower())
        log_method(
            "Agent tool returned catalogued error %s",
            exc.code,
            extra={
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "error_code": exc.code,
            },
        )
        return AgentToolResult[ToolData](ok=False, error=error)
    except SQLAlchemyError as exc:
        logger.error(
            "Agent tool database operation failed (%s); exception details omitted",
            type(exc).__name__,
            extra={
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "error_code": "DATABASE_ERROR",
            },
        )
        return AgentToolResult[ToolData](
            ok=False,
            error=_catalog_error("DATABASE_ERROR"),
        )
    except Exception as exc:
        logger.error(
            "Agent tool failed unexpectedly (%s); exception details omitted",
            type(exc).__name__,
            extra={
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "error_code": "INTERNAL_ERROR",
            },
        )
        return AgentToolResult[ToolData](
            ok=False,
            error=_catalog_error("INTERNAL_ERROR"),
        )

    logger.info(
        "Agent tool completed",
        extra={"tool_name": tool_name, "tool_call_id": tool_call_id},
    )
    return AgentToolResult[ToolData](ok=True, data=data)


def _service_item(service: DentalService) -> DentalServiceToolItem:
    return DentalServiceToolItem(
        id=service.id,
        name=service.name,
        description=service.description,
    )


def _doctor_item(doctor: Doctor) -> DoctorToolItem:
    return DoctorToolItem(
        id=doctor.id,
        full_name=doctor.full_name,
        specialty=doctor.specialty,
    )


async def search_dental_services(
    db: AsyncSession,
    query: str | None = None,
) -> AgentToolResult[list[DentalServiceToolItem]]:
    """Search active services by an optional partial name match."""

    async def operation() -> list[DentalServiceToolItem]:
        request = SearchDentalServicesInput(query=query)
        services = await dental_service_service.search_dental_services(
            db,
            request.query,
        )
        return [_service_item(service) for service in services]

    return await _execute_tool("search_dental_services", operation)


async def find_doctors_for_service(
    db: AsyncSession,
    service_id: int,
) -> AgentToolResult[list[DoctorToolItem]]:
    """List active doctors that provide the requested active service."""

    async def operation() -> list[DoctorToolItem]:
        request = FindDoctorsForServiceInput(service_id=service_id)
        doctors = await dental_service_service.get_service_doctors(
            db,
            request.service_id,
        )
        return [_doctor_item(doctor) for doctor in doctors]

    return await _execute_tool("find_doctors_for_service", operation)


async def find_available_slots(
    db: AsyncSession,
    service_id: int,
    doctor_id: int,
    appointment_date: str,
) -> AgentToolResult[AvailableSlotsToolData]:
    """Return service-valid free start times; never infer or fabricate slots."""

    async def operation() -> AvailableSlotsToolData:
        request = FindAvailableSlotsInput(
            service_id=service_id,
            doctor_id=doctor_id,
            appointment_date=appointment_date,
        )
        slots = await appointment_service.get_available_slots(
            db,
            request.doctor_id,
            request.appointment_date,
            service_id=request.service_id,
        )
        return AvailableSlotsToolData(
            service_id=request.service_id,
            doctor_id=request.doctor_id,
            appointment_date=request.appointment_date,
            available_slots=slots,
        )

    return await _execute_tool("find_available_slots", operation)


async def find_nearest_appointments(
    db: AsyncSession,
    *,
    service_id: int | None = None,
    doctor_id: int | None = None,
    days: int = 30,
    limit: int = 3,
) -> AgentToolResult[NearestAppointmentsToolData]:
    """Return the earliest free slots across a forward range, no date needed."""

    async def operation() -> NearestAppointmentsToolData:
        request = FindNearestAppointmentsInput(
            service_id=service_id,
            doctor_id=doctor_id,
            days=days,
            limit=limit,
        )
        slots = await appointment_service.find_nearest_available_slots(
            db,
            service_id=request.service_id,
            doctor_id=request.doctor_id,
            days=request.days,
            limit=request.limit,
        )
        return NearestAppointmentsToolData(
            search_days=request.days,
            appointments=[
                NearestAppointmentToolItem(**slot) for slot in slots
            ],
        )

    return await _execute_tool("find_nearest_appointments", operation)


async def get_patient_appointments(
    db: AsyncSession,
    patient_id: int,
) -> AgentToolResult[list[PatientAppointmentToolItem]]:
    """Return minimal appointment facts, excluding free-text patient reasons."""

    async def operation() -> list[PatientAppointmentToolItem]:
        request = GetPatientAppointmentsInput(patient_id=patient_id)
        appointments = await appointment_service.get_patient_appointments(
            db,
            request.patient_id,
        )
        return [_appointment_item(appointment) for appointment in appointments]

    return await _execute_tool("get_patient_appointments", operation)


async def book_appointment(
    db: AsyncSession,
    *,
    doctor_id: int,
    service_id: int,
    appointment_date: str,
    appointment_time: str,
    patient_id: int | None = None,
    national_id: str | None = None,
    full_name: str | None = None,
    phone: str | None = None,
    reason: str | None = None,
) -> AgentToolResult[BookAppointmentToolData]:
    """Book through BookingService; patient PII is never returned or logged."""

    async def operation() -> BookAppointmentToolData:
        request = BookAppointmentInput(
            doctor_id=doctor_id,
            service_id=service_id,
            appointment_date=appointment_date,
            appointment_time=appointment_time,
            patient_id=patient_id,
            national_id=national_id,
            full_name=full_name,
            phone=phone,
            reason=reason,
        )
        appointment = await booking_service.create_booking(
            db=db,
            doctor_id=request.doctor_id,
            service_id=request.service_id,
            appointment_date=request.appointment_date,
            appointment_time=request.appointment_time,
            patient_id=request.patient_id,
            national_id=request.national_id,
            full_name=request.full_name,
            phone=request.phone,
            reason=request.reason,
        )
        jalali_date, appointment_clock = gregorian_to_jalali(
            appointment.appointment_time
        )
        return BookAppointmentToolData(
            appointment_id=appointment.id,
            patient_id=appointment.patient_id,
            doctor_id=appointment.doctor_id,
            service_id=appointment.service_id,
            appointment_time=f"{jalali_date} {appointment_clock}",
            status=appointment.status,
        )

    return await _execute_tool("book_appointment", operation)


async def cancel_appointment(
    db: AsyncSession,
    appointment_id: int,
) -> AgentToolResult[CancelAppointmentToolData]:
    """Cancel a scheduled appointment through AppointmentService."""

    async def operation() -> CancelAppointmentToolData:
        request = CancelAppointmentInput(appointment_id=appointment_id)
        appointment = await appointment_service.cancel_appointment(
            db,
            request.appointment_id,
        )
        return CancelAppointmentToolData(
            appointment_id=appointment.id,
            status=appointment.status,
        )

    return await _execute_tool("cancel_appointment", operation)


async def reschedule_appointment(
    db: AsyncSession,
    appointment_id: int,
    appointment_date: str,
    appointment_time: str,
) -> AgentToolResult[RescheduleAppointmentToolData]:
    """Reschedule through AppointmentService; do not expose patient details."""

    async def operation() -> RescheduleAppointmentToolData:
        request = RescheduleAppointmentInput(
            appointment_id=appointment_id,
            appointment_date=appointment_date,
            appointment_time=appointment_time,
        )
        appointment = await appointment_service.reschedule_appointment(
            db,
            request.appointment_id,
            request.appointment_date,
            request.appointment_time,
        )
        jalali_date, appointment_clock = gregorian_to_jalali(
            appointment.appointment_time
        )
        return RescheduleAppointmentToolData(
            appointment_id=appointment.id,
            patient_id=appointment.patient_id,
            doctor_id=appointment.doctor_id,
            service_id=appointment.service_id,
            appointment_time=f"{jalali_date} {appointment_clock}",
            status=appointment.status,
        )

    return await _execute_tool("reschedule_appointment", operation)


def _appointment_item(
    appointment: Appointment,
) -> PatientAppointmentToolItem:
    appointment_date, appointment_time = gregorian_to_jalali(
        appointment.appointment_time
    )
    return PatientAppointmentToolItem(
        appointment_id=appointment.id,
        doctor_id=appointment.doctor_id,
        service_id=appointment.service_id,
        appointment_date=appointment_date,
        appointment_time=appointment_time,
        status=appointment.status,
    )
