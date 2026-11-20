"""Agent-facing adapters that delegate operations to application services."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_tools.schemas import (
    AgentToolError,
    AgentToolResult,
    AuditTrailInput,
    AuditTrailItem,
    AuditTrailToolData,
    AvailableSlotsToolData,
    BookAppointmentInput,
    BookAppointmentToolData,
    CancelAppointmentInput,
    CancelAppointmentToolData,
    ClinicAppointmentsReportToolData,
    ClinicOverviewStatsToolData,
    CreatePatientInput,
    CreatePatientToolData,
    DayPlanAppointmentItem,
    DentalServiceToolItem,
    DoctorAppointmentStatItem,
    DoctorDayPlanToolData,
    DoctorScheduleItem,
    DoctorSchedulesToolData,
    DoctorToolItem,
    FeedbackItem,
    FeedbackSummaryToolData,
    FindAvailableSlotsInput,
    FindDoctorsForServiceInput,
    FindNearestAppointmentsInput,
    GetClinicAppointmentsReportInput,
    GetDoctorDayPlanInput,
    GetDoctorSchedulesInput,
    GetPatientAppointmentsInput,
    MyProfileRecordItem,
    MyProfileToolData,
    NearestAppointmentsToolData,
    NearestAppointmentToolItem,
    PatientAppointmentToolItem,
    PatientSearchToolItem,
    PatientSummaryAppointmentItem,
    PatientSummaryInput,
    PatientSummaryToolData,
    RescheduleAppointmentInput,
    RescheduleAppointmentToolData,
    SearchDentalServicesInput,
    SearchPatientsInput,
    StaffDirectoryItem,
    StaffDirectoryToolData,
    SubmitFeedbackInput,
    SubmitFeedbackToolData,
    UpdatePatientInput,
    UpdatePatientToolData,
)
from app.auth.permissions import (
    actor_role,
    authorize_tool_call,
    ensure_doctor_listing_scope,
)
from app.errors import ERROR_CATALOG, AppError
from app.models.appointment import Appointment
from app.models.audit_log import AuditLog
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_schedule import DoctorSchedule
from app.models.feedback import FeedbackReport
from app.models.user import User
from app.services import (
    appointment_service,
    booking_service,
    dental_service_service,
    patient_service,
    report_service,
)
from app.services.audit_service import record_audit
from app.utils.date_utils import gregorian_to_jalali, jalali_to_gregorian

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
    *,
    internal: dict[str, Any] | None = None,
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
    return AgentToolResult[ToolData](
        ok=True,
        data=data,
        internal=dict(internal or {}),
    )


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


def _mask_national_id(national_id: str | None) -> str | None:
    """Keep only a short, non-identifying tail of the national id."""
    if not national_id:
        return None
    digits = "".join(char for char in str(national_id) if char.isdigit())
    if len(digits) < 4:
        return "***"
    return f"***{digits[-3:]}"


# ``DoctorSchedule.day_of_week`` and ``saturday_based_day_of_week`` both use
# Saturday=0 through Friday=6.
_SATURDAY_BASED_WEEKDAYS = (
    "شنبه",
    "یکشنبه",
    "دوشنبه",
    "سه‌شنبه",
    "چهارشنبه",
    "پنجشنبه",
    "جمعه",
)


def _weekday_name(day_index: int) -> str:
    if 0 <= day_index <= 6:
        return _SATURDAY_BASED_WEEKDAYS[day_index]
    return "نامشخص"


def _summary_item(
    item: PatientAppointmentToolItem,
) -> PatientSummaryAppointmentItem:
    """Convert a model-visible row into the summary-card row type."""
    return PatientSummaryAppointmentItem(
        appointment_date=item.appointment_date,
        appointment_time=item.appointment_time,
        doctor_name=item.doctor_name,
        service_name=item.service_name,
        status=item.status,
    )


async def search_dental_services(
    db: AsyncSession,
    query: str | None = None,
    *,
    limit: int = 10,
    actor: User | None = None,
) -> AgentToolResult[list[DentalServiceToolItem]]:
    """Search active services by short Persian keyword(s)."""

    async def operation() -> list[DentalServiceToolItem]:
        request = SearchDentalServicesInput(query=query, limit=limit)
        await authorize_tool_call(
            db,
            actor,
            "search_dental_services",
            request.model_dump(),
        )
        services = await dental_service_service.search_dental_services(
            db,
            request.query,
            limit=request.limit,
        )
        return [_service_item(service) for service in services]

    return await _execute_tool("search_dental_services", operation)


async def find_doctors_for_service(
    db: AsyncSession,
    service_id: int,
    *,
    actor: User | None = None,
) -> AgentToolResult[list[DoctorToolItem]]:
    """List active doctors that provide the requested active service."""

    async def operation() -> list[DoctorToolItem]:
        request = FindDoctorsForServiceInput(service_id=service_id)
        await authorize_tool_call(
            db,
            actor,
            "find_doctors_for_service",
            request.model_dump(),
        )
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
    *,
    actor: User | None = None,
) -> AgentToolResult[AvailableSlotsToolData]:
    """Return service-valid free start times; never infer or fabricate slots."""

    async def operation() -> AvailableSlotsToolData:
        request = FindAvailableSlotsInput(
            service_id=service_id,
            doctor_id=doctor_id,
            appointment_date=appointment_date,
        )
        await authorize_tool_call(
            db,
            actor,
            "find_available_slots",
            request.model_dump(),
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
    service_id: int,
    doctor_id: int | None = None,
    days: int = 30,
    limit: int = 3,
    actor: User | None = None,
) -> AgentToolResult[NearestAppointmentsToolData]:
    """Return the earliest free slots across a forward range, no date needed."""

    async def operation() -> NearestAppointmentsToolData:
        request = FindNearestAppointmentsInput(
            service_id=service_id,
            doctor_id=doctor_id,
            days=days,
            limit=limit,
        )
        await authorize_tool_call(
            db,
            actor,
            "find_nearest_appointments",
            request.model_dump(),
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
    *,
    actor: User | None = None,
) -> AgentToolResult[list[PatientAppointmentToolItem]]:
    """Return minimal appointment facts without internal ids or free text."""

    async def operation() -> list[PatientAppointmentToolItem]:
        request = GetPatientAppointmentsInput(patient_id=patient_id)
        # Ownership is enforced here as well as in the graph. A direct caller
        # cannot use a forged patient_id to read another patient's rows.
        await authorize_tool_call(
            db,
            actor,
            "get_patient_appointments",
            request.model_dump(),
        )
        appointments = await appointment_service.get_patient_appointments(
            db,
            request.patient_id,
        )
        return [
            await _appointment_item(db, appointment)
            for appointment in appointments
        ]

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
    actor: User | None = None,
) -> AgentToolResult[BookAppointmentToolData]:
    """Book through BookingService; patient PII is never returned or logged."""

    internal: dict[str, Any] = {}

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
        await authorize_tool_call(
            db,
            actor,
            "book_appointment",
            request.model_dump(),
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
            actor_role=actor_role(actor),
        )
        jalali_date, appointment_clock = gregorian_to_jalali(
            appointment.appointment_time
        )
        # The row id stays server-side for success messaging and id redaction.
        internal["appointment_id"] = appointment.id
        return BookAppointmentToolData(
            appointment_time=f"{jalali_date} {appointment_clock}",
            status=appointment.status,
        )

    return await _execute_tool(
        "book_appointment",
        operation,
        internal=internal,
    )


async def cancel_appointment(
    db: AsyncSession,
    appointment_id: int | None = None,
    *,
    actor: User | None = None,
) -> AgentToolResult[CancelAppointmentToolData]:
    """Cancel a scheduled appointment through AppointmentService."""

    internal: dict[str, Any] = {}

    async def operation() -> CancelAppointmentToolData:
        request = CancelAppointmentInput(appointment_id=appointment_id)
        if request.appointment_id is None:
            # The graph must resolve a concrete target before execution. A
            # missing id here is a validation failure, not an implicit choice.
            raise AppError("COMMON_VALIDATION_ERROR")
        await authorize_tool_call(
            db,
            actor,
            "cancel_appointment",
            request.model_dump(),
        )
        appointment = await appointment_service.cancel_appointment(
            db,
            request.appointment_id,
            actor_role=actor_role(actor),
        )
        internal["appointment_id"] = appointment.id
        return CancelAppointmentToolData(status=appointment.status)

    return await _execute_tool(
        "cancel_appointment",
        operation,
        internal=internal,
    )


async def reschedule_appointment(
    db: AsyncSession,
    appointment_id: int | None = None,
    appointment_date: str | None = None,
    appointment_time: str | None = None,
    *,
    actor: User | None = None,
) -> AgentToolResult[RescheduleAppointmentToolData]:
    """Reschedule through AppointmentService; do not expose patient details."""

    internal: dict[str, Any] = {}

    async def operation() -> RescheduleAppointmentToolData:
        if appointment_date is None or appointment_time is None:
            raise AppError("COMMON_VALIDATION_ERROR")
        request = RescheduleAppointmentInput(
            appointment_id=appointment_id,
            appointment_date=appointment_date,
            appointment_time=appointment_time,
        )
        if request.appointment_id is None:
            raise AppError("COMMON_VALIDATION_ERROR")
        await authorize_tool_call(
            db,
            actor,
            "reschedule_appointment",
            request.model_dump(),
        )
        appointment = await appointment_service.reschedule_appointment(
            db,
            request.appointment_id,
            request.appointment_date,
            request.appointment_time,
            actor_role=actor_role(actor),
        )
        jalali_date, appointment_clock = gregorian_to_jalali(
            appointment.appointment_time
        )
        internal["appointment_id"] = appointment.id
        return RescheduleAppointmentToolData(
            appointment_time=f"{jalali_date} {appointment_clock}",
            status=appointment.status,
        )

    return await _execute_tool(
        "reschedule_appointment",
        operation,
        internal=internal,
    )


async def get_clinic_appointments_report(
    db: AsyncSession,
    *,
    window_days: int = 30,
    actor: User | None = None,
) -> AgentToolResult[ClinicAppointmentsReportToolData]:
    """Real appointment workload aggregate; staff-only (server-side role check)."""

    async def operation() -> ClinicAppointmentsReportToolData:
        request = GetClinicAppointmentsReportInput(window_days=window_days)
        await authorize_tool_call(
            db,
            actor,
            "get_clinic_appointments_report",
            request.model_dump(),
        )
        report = await report_service.clinic_appointments_report(
            db, window_days=request.window_days
        )
        return ClinicAppointmentsReportToolData(
            generated_at=str(report["generated_at"]),
            window_days=int(report["window_days"]),
            today_appointments=int(report["today_appointments"]),
            upcoming_scheduled=int(report["upcoming_scheduled"]),
            upcoming_cancelled=int(report["upcoming_cancelled"]),
            doctor_load=[
                DoctorAppointmentStatItem(
                    doctor_id=int(item["doctor_id"]),
                    doctor_name=str(item["doctor_name"]),
                    scheduled_count=int(item["scheduled_count"]),
                )
                for item in report["doctor_load"]
            ],
        )

    return await _execute_tool("get_clinic_appointments_report", operation)


async def get_clinic_overview_stats(
    db: AsyncSession,
    *,
    actor: User | None = None,
) -> AgentToolResult[ClinicOverviewStatsToolData]:
    """Whole-clinic overview; admin-only by server-side role permission."""

    async def operation() -> ClinicOverviewStatsToolData:
        await authorize_tool_call(
            db,
            actor,
            "get_clinic_overview_stats",
            {},
        )
        stats = await report_service.clinic_overview_stats(db)
        return ClinicOverviewStatsToolData(
            generated_at=str(stats["generated_at"]),
            patients_total=int(stats["patients_total"]),
            patients_incomplete=int(stats["patients_incomplete"]),
            doctors_total=int(stats["doctors_total"]),
            services_total=int(stats["services_total"]),
            appointments_upcoming=int(stats["appointments_upcoming"]),
            appointments_today=int(stats["appointments_today"]),
            cancellations_30d=int(stats["cancellations_30d"]),
        )

    return await _execute_tool("get_clinic_overview_stats", operation)


async def _appointment_item(
    db: AsyncSession,
    appointment: Appointment,
) -> PatientAppointmentToolItem:
    """Build a model-visible row without exposing internal ids.

    Names are read from the database, not from model input, so the model can
    discuss which appointment the user means without receiving a row id.
    """
    appointment_date, appointment_time = gregorian_to_jalali(
        appointment.appointment_time
    )
    doctor = await db.get(Doctor, appointment.doctor_id)
    service = await db.get(DentalService, appointment.service_id)
    return PatientAppointmentToolItem(
        doctor_name=doctor.full_name if doctor is not None else "پزشک ثبت‌شده",
        service_name=(
            service.name if service is not None else "خدمت ثبت‌شده"
        ),
        appointment_date=appointment_date,
        appointment_time=appointment_time,
        status=appointment.status,
    )


async def search_patients(
    db: AsyncSession,
    query: str | None = None,
    *,
    limit: int = 10,
    actor: User | None = None,
) -> AgentToolResult[list[PatientSearchToolItem]]:
    """Front-desk lookup by name/phone/national-id fragment; staff-only.

    The national id is masked before the model sees it. Phone numbers stay
    complete because calling the patient back is exactly the front-desk job
    this tool supports.
    """

    async def operation() -> list[PatientSearchToolItem]:
        request = SearchPatientsInput(query=query, limit=limit)
        await authorize_tool_call(
            db,
            actor,
            "search_patients",
            request.model_dump(),
        )
        patients = await patient_service.list_patients(
            db,
            search=request.query,
        )
        return [
            PatientSearchToolItem(
                id=patient.id,
                full_name=patient.full_name,
                phone=patient.phone,
                national_id_masked=_mask_national_id(patient.national_id),
                record_status=patient.record_status,
            )
            for patient in patients[: request.limit]
        ]

    return await _execute_tool("search_patients", operation)


async def get_patient_summary(
    db: AsyncSession,
    patient_id: int,
    *,
    actor: User | None = None,
) -> AgentToolResult[PatientSummaryToolData]:
    """Bounded patient card: identity facts, counters, next and past visits."""

    async def operation() -> PatientSummaryToolData:
        request = PatientSummaryInput(patient_id=patient_id)
        await authorize_tool_call(
            db,
            actor,
            "get_patient_summary",
            request.model_dump(),
        )
        patient = await patient_service.get_patient(db, request.patient_id)
        appointments = await appointment_service.get_patient_appointments(
            db,
            request.patient_id,
        )
        current = appointment_service.clinic_now()
        # (row, item) pairs keep the raw datetime for ordering decisions.
        pairs: list[tuple[Appointment, PatientSummaryAppointmentItem]] = []
        for appointment in appointments:
            item = await _appointment_item(db, appointment)
            pairs.append((appointment, item))
        upcoming = [
            _summary_item(item)
            for appointment, item in pairs
            if appointment.status == "scheduled"
            and appointment.appointment_time >= current
        ]
        past = [
            _summary_item(item)
            for appointment, item in pairs
            if appointment.appointment_time < current
        ]
        return PatientSummaryToolData(
            patient_id=int(patient.id),
            full_name=patient.full_name,
            phone=patient.phone,
            national_id_masked=_mask_national_id(patient.national_id),
            record_status=patient.record_status,
            is_account_holder=bool(patient.is_account_holder),
            upcoming_count=len(upcoming),
            next_appointment=upcoming[0] if upcoming else None,
            recent_appointments=list(reversed(past))[:5],
        )

    return await _execute_tool("get_patient_summary", operation)


async def get_doctor_schedules(
    db: AsyncSession,
    doctor_id: int | None = None,
    *,
    actor: User | None = None,
) -> AgentToolResult[DoctorSchedulesToolData]:
    """Weekly working blocks of active doctors; visible to every role."""

    async def operation() -> DoctorSchedulesToolData:
        request = GetDoctorSchedulesInput(doctor_id=doctor_id)
        await authorize_tool_call(
            db,
            actor,
            "get_doctor_schedules",
            request.model_dump(),
        )
        query = (
            select(DoctorSchedule, Doctor)
            .join(Doctor, DoctorSchedule.doctor_id == Doctor.id)
            .where(
                Doctor.is_active.is_(True),
                DoctorSchedule.is_active.is_(True),
            )
            .order_by(
                Doctor.id,
                DoctorSchedule.day_of_week,
                DoctorSchedule.start_time,
            )
        )
        if request.doctor_id is not None:
            query = query.where(DoctorSchedule.doctor_id == request.doctor_id)
        rows = (await db.execute(query)).all()
        if request.doctor_id is not None and not rows:
            raise AppError("DOCTOR_SCHEDULE_NOT_FOUND")
        return DoctorSchedulesToolData(
            schedules=[
                DoctorScheduleItem(
                    doctor_id=int(schedule.doctor_id),
                    doctor_name=doctor.full_name,
                    specialty=doctor.specialty,
                    weekday=_weekday_name(schedule.day_of_week),
                    start_time=schedule.start_time.strftime("%H:%M"),
                    end_time=schedule.end_time.strftime("%H:%M"),
                    slot_duration_minutes=int(schedule.slot_duration_minutes),
                )
                for schedule, doctor in rows
            ]
        )

    return await _execute_tool("get_doctor_schedules", operation)


async def get_doctor_day_plan(
    db: AsyncSession,
    appointment_date: str | None = None,
    doctor_id: int | None = None,
    *,
    actor: User | None = None,
) -> AgentToolResult[DoctorDayPlanToolData]:
    """One doctor's agenda for one Jalali day; doctor accounts auto-scoped.

    Admin/receptionist must name a doctor. A doctor-role account is pinned to
    its own linked record by ``ensure_doctor_listing_scope`` (both here and in
    ``authorize_tool_call``), so the plan can never widen by passing ids.
    """

    async def operation() -> DoctorDayPlanToolData:
        request = GetDoctorDayPlanInput(
            appointment_date=appointment_date,
            doctor_id=doctor_id,
        )
        await authorize_tool_call(
            db,
            actor,
            "get_doctor_day_plan",
            request.model_dump(),
        )
        effective_doctor_id = await ensure_doctor_listing_scope(
            db,
            actor,
            request.doctor_id,
        )
        if effective_doctor_id is None:
            # Admin/receptionist without a doctor choice: a day plan without
            # a doctor is ambiguous, so the model asks a clear question.
            raise AppError("COMMON_VALIDATION_ERROR")
        if request.appointment_date is not None:
            try:
                day_start = jalali_to_gregorian(
                    request.appointment_date,
                    "00:00",
                )
            except ValueError as exc:
                raise AppError("APPOINTMENT_INVALID_DATE") from exc
            # A fresh local name: assigning the outer ``appointment_date``
            # parameter would make it operation-local and break its first read.
            day_date = request.appointment_date
        else:
            current = appointment_service.clinic_now()
            day_start = current.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            day_date, _ = gregorian_to_jalali(day_start)

        details = await appointment_service.get_appointments_detail(
            db,
            doctor_id=effective_doctor_id,
            appointment_date=day_date,
        )
        doctor = await db.get(Doctor, effective_doctor_id)
        day_index = appointment_service.saturday_based_day_of_week(
            day_start.date()
        )
        schedule_rows = (
            await db.execute(
                select(DoctorSchedule).where(
                    DoctorSchedule.doctor_id == effective_doctor_id,
                    DoctorSchedule.day_of_week == day_index,
                    DoctorSchedule.is_active.is_(True),
                )
            )
        ).scalars().all()
        working_hours: str | None = None
        if schedule_rows:
            spans = "، ".join(
                f"{row.start_time.strftime('%H:%M')} تا "
                f"{row.end_time.strftime('%H:%M')}"
                for row in schedule_rows
            )
            working_hours = spans
        items = sorted(
            (
                DayPlanAppointmentItem(
                    appointment_id=int(detail["id"]),
                    patient_name=str(detail["patient_name"]),
                    service_name=str(detail["service_name"]),
                    appointment_time=str(detail["appointment_time"]),
                    status=str(detail["status"]),
                    reason=(
                        str(detail["reason"])
                        if detail.get("reason") is not None
                        else None
                    ),
                )
                for detail in details
            ),
            key=lambda item: item.appointment_time,
        )
        return DoctorDayPlanToolData(
            doctor_id=effective_doctor_id,
            doctor_name=(
                doctor.full_name if doctor is not None else "پزشک ثبت‌شده"
            ),
            appointment_date=day_date,
            weekday=_weekday_name(day_index),
            working_hours=working_hours,
            appointments=items,
        )

    return await _execute_tool("get_doctor_day_plan", operation)


async def get_user_reports_summary(
    db: AsyncSession,
    *,
    actor: User | None = None,
) -> AgentToolResult[FeedbackSummaryToolData]:
    """Admin-only snapshot of the user reports inbox; previews only."""

    async def operation() -> FeedbackSummaryToolData:
        await authorize_tool_call(db, actor, "get_user_reports_summary", {})
        total_row = await db.execute(select(func.count(FeedbackReport.id)))
        total = int(total_row.scalar_one())
        category_rows = await db.execute(
            select(FeedbackReport.category, func.count(FeedbackReport.id))
            .group_by(FeedbackReport.category)
        )
        status_rows = await db.execute(
            select(FeedbackReport.status, func.count(FeedbackReport.id))
            .group_by(FeedbackReport.status)
        )
        recent_rows = (
            (
                await db.execute(
                    select(FeedbackReport)
                    .order_by(
                        FeedbackReport.created_at.desc(),
                        FeedbackReport.id.desc(),
                    )
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
        return FeedbackSummaryToolData(
            total=total,
            by_category={
                category: int(count)
                for category, count in category_rows.all()
            },
            by_status={
                status: int(count) for status, count in status_rows.all()
            },
            recent=[
                FeedbackItem(
                    id=int(report.id),
                    category=report.category,
                    status=report.status,
                    created_at=" ".join(gregorian_to_jalali(report.created_at)),
                    message_preview=report.message[:120],
                )
                for report in recent_rows
            ],
        )

    return await _execute_tool("get_user_reports_summary", operation)


async def get_my_profile(
    db: AsyncSession,
    *,
    actor: User | None = None,
) -> AgentToolResult[MyProfileToolData]:
    """Self-service card of the records owned by the authenticated patient.

    Server-side ownership only: the record list comes from the account's
    linked rows, never from client input, and the national id is never
    included in the model-visible payload.
    """

    async def operation() -> MyProfileToolData:
        await authorize_tool_call(db, actor, "get_my_profile", {})
        patients = await patient_service.get_patients_by_user_id(
            db,
            int(actor.id),
        )
        current = appointment_service.clinic_now()
        records: list[MyProfileRecordItem] = []
        for patient in patients:
            appointments = await appointment_service.get_patient_appointments(
                db,
                int(patient.id),
            )
            upcoming: list[PatientSummaryAppointmentItem] = []
            for appointment in appointments:
                if (
                    appointment.status == "scheduled"
                    and appointment.appointment_time >= current
                ):
                    item = await _appointment_item(db, appointment)
                    upcoming.append(_summary_item(item))
            records.append(
                MyProfileRecordItem(
                    patient_id=int(patient.id),
                    full_name=patient.full_name,
                    phone=patient.phone,
                    relation=(
                        "صاحب حساب"
                        if patient.is_account_holder
                        else "عضو خانواده"
                    ),
                    record_status=patient.record_status,
                    upcoming_count=len(upcoming),
                    next_appointment=upcoming[0] if upcoming else None,
                )
            )
        return MyProfileToolData(records=records)

    return await _execute_tool("get_my_profile", operation)


async def create_patient(
    db: AsyncSession,
    national_id: str,
    full_name: str,
    phone: str,
    *,
    actor: User | None = None,
) -> AgentToolResult[CreatePatientToolData]:
    """Register a new patient record through the front-desk service.

    The service normalizes ids/phones, rejects duplicates with catalogued
    errors and commits atomically; the audit row is flushed afterwards and
    persisted with the chat turn's own commit.
    """

    internal: dict[str, Any] = {}

    async def operation() -> CreatePatientToolData:
        request = CreatePatientInput(
            national_id=national_id,
            full_name=full_name,
            phone=phone,
        )
        await authorize_tool_call(db, actor, "create_patient", request.model_dump())
        patient = await patient_service.create_patient(
            db,
            request.national_id,
            request.full_name,
            request.phone,
        )
        internal["patient_id"] = patient.id
        await record_audit(
            db,
            actor=actor,
            action="patient.create",
            target_label=f"{patient.full_name} ({patient.phone})",
            detail={"via": "agent"},
        )
        return CreatePatientToolData(
            full_name=patient.full_name,
            phone=patient.phone,
            record_status=patient.record_status,
        )

    return await _execute_tool(
        "create_patient",
        operation,
        internal=internal,
    )


async def update_patient(
    db: AsyncSession,
    patient_id: int,
    full_name: str | None = None,
    phone: str | None = None,
    national_id: str | None = None,
    *,
    actor: User | None = None,
) -> AgentToolResult[UpdatePatientToolData]:
    """Edit an existing record; omitted fields keep their current values."""

    async def operation() -> UpdatePatientToolData:
        request = UpdatePatientInput(
            patient_id=patient_id,
            full_name=full_name,
            phone=phone,
            national_id=national_id,
        )
        await authorize_tool_call(db, actor, "update_patient", request.model_dump())
        current = await patient_service.get_patient(db, request.patient_id)
        patient = await patient_service.update_patient(
            db,
            request.patient_id,
            full_name=(
                request.full_name
                if request.full_name is not None
                else current.full_name
            ),
            phone=(
                request.phone if request.phone is not None else current.phone
            ),
            national_id=(
                request.national_id
                if request.national_id is not None
                else current.national_id
            ),
        )
        await record_audit(
            db,
            actor=actor,
            action="patient.update",
            target_label=f"{patient.full_name} ({patient.phone})",
            detail={
                "via": "agent",
                "changed": [
                    field
                    for field in ("full_name", "phone", "national_id")
                    if getattr(request, field) is not None
                ],
            },
        )
        return UpdatePatientToolData(
            full_name=patient.full_name,
            phone=patient.phone,
            national_id_masked=_mask_national_id(patient.national_id),
            record_status=patient.record_status,
        )

    return await _execute_tool("update_patient", operation)


async def get_staff_directory(
    db: AsyncSession,
    *,
    actor: User | None = None,
) -> AgentToolResult[StaffDirectoryToolData]:
    """Administrator-only account overview; never returns password data."""

    async def operation() -> StaffDirectoryToolData:
        await authorize_tool_call(db, actor, "get_staff_directory", {})
        rows = (
            await db.execute(select(User).order_by(User.id))
        ).scalars().all()
        by_role: dict[str, int] = {}
        active = 0
        for row in rows:
            by_role[row.role] = by_role.get(row.role, 0) + 1
            if row.is_active:
                active += 1
        recent = sorted(
            rows,
            key=lambda row: (
                row.last_login_at is not None,
                row.last_login_at or row.created_at,
            ),
            reverse=True,
        )[:5]
        return StaffDirectoryToolData(
            total_accounts=len(rows),
            by_role=by_role,
            active_accounts=active,
            inactive_accounts=len(rows) - active,
            recent_accounts=[
                StaffDirectoryItem(
                    user_id=int(row.id),
                    full_name=row.full_name,
                    role=row.role,
                    is_active=bool(row.is_active),
                    last_login_at=(
                        " ".join(gregorian_to_jalali(row.last_login_at))
                        if row.last_login_at is not None
                        else None
                    ),
                )
                for row in recent
            ],
        )

    return await _execute_tool("get_staff_directory", operation)


async def get_audit_trail(
    db: AsyncSession,
    limit: int = 10,
    *,
    actor: User | None = None,
) -> AgentToolResult[AuditTrailToolData]:
    """Newest append-only audit rows; administrator-only review."""

    async def operation() -> AuditTrailToolData:
        request = AuditTrailInput(limit=limit)
        await authorize_tool_call(
            db,
            actor,
            "get_audit_trail",
            request.model_dump(),
        )
        rows = (
            (
                await db.execute(
                    select(AuditLog)
                    .order_by(
                        AuditLog.created_at.desc(), AuditLog.id.desc()
                    )
                    .limit(request.limit)
                )
            )
            .scalars()
            .all()
        )
        return AuditTrailToolData(
            total_returned=len(rows),
            entries=[
                AuditTrailItem(
                    action=row.action,
                    actor_phone=row.actor_phone,
                    target_label=row.target_label,
                    created_at=" ".join(gregorian_to_jalali(row.created_at)),
                    detail=dict(row.detail) if row.detail else None,
                )
                for row in rows
            ],
        )

    return await _execute_tool("get_audit_trail", operation)


async def submit_feedback(
    db: AsyncSession,
    category: str,
    message: str,
    *,
    actor: User | None = None,
) -> AgentToolResult[SubmitFeedbackToolData]:
    """Store an in-chat error report or suggestion for the acting account.

    The row is scoped server-side to the authenticated account; nothing from
    model-supplied identity is trusted, and the message length mirrors the
    HTTP feedback endpoint's limit.
    """

    internal: dict[str, Any] = {}

    async def operation() -> SubmitFeedbackToolData:
        request = SubmitFeedbackInput(category=category, message=message)
        await authorize_tool_call(db, actor, "submit_feedback", request.model_dump())
        report = FeedbackReport(
            user_id=int(actor.id) if actor is not None else None,
            category=request.category,
            message=request.message,
            context={"source": "agent", "role": actor.role}
            if actor is not None
            else {"source": "agent"},
            status="new",
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)
        internal["feedback_id"] = report.id
        return SubmitFeedbackToolData(status="received")

    return await _execute_tool(
        "submit_feedback",
        operation,
        internal=internal,
    )
