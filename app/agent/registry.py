"""Allowlisted Agent Tool metadata and handlers."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from app.agent_tools import tools
from app.agent_tools.schemas import (
    AgentToolResult,
    AuditTrailInput,
    BookAppointmentInput,
    CancelAppointmentInput,
    ClinicOverviewStatsInput,
    CreatePatientInput,
    CreateTreatmentPlanDraftInput,
    FeedbackSummaryInput,
    FindAvailableSlotsInput,
    FindDoctorsForServiceInput,
    FindNearestAppointmentsInput,
    GetClinicAppointmentsReportInput,
    GetDoctorDayPlanInput,
    GetDoctorSchedulesInput,
    GetPatientAppointmentsInput,
    GetPatientClinicalSummaryInput,
    MyProfileInput,
    PatientSummaryInput,
    RescheduleAppointmentInput,
    SearchDentalServicesInput,
    SearchPatientsInput,
    StaffDirectoryInput,
    SubmitFeedbackInput,
    UpdatePatientInput,
)
from app.auth.permissions import action_default_roles, role_allows, tool_action
from app.models.user import User

ToolHandler = Callable[..., Awaitable[AgentToolResult[Any]]]


def _staff_tool_visible(
    definition: object,
    role: str | None,
    actor: User | None,
) -> bool:
    """Whether a staff-only tool may be offered to this staff session.

    Visibility follows the coarse role matrix; a concrete ``actor`` with a
    pinned ``allow`` override wins over the matrix so an administrator can
    hand a doctor record-management tools without code changes.
    """
    action = tool_action(definition.name)
    if action is None:
        return True
    if actor is not None:
        return role_allows(actor, action)
    return role is not None and role in action_default_roles(action)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    operation: Literal["read", "write"]
    description: str
    input_schema: type[BaseModel]
    handler: ToolHandler
    # Staff-only tools are not even shown to patient-bound model sessions.
    # This is a usability filter; ``authorize_tool_call`` stays the boundary.
    staff_only: bool = False
    # Admin-only tools are additionally hidden from receptionist/doctor
    # sessions. Again a visibility filter only; the authorization layer
    # remains the real boundary for every tool.
    admin_only: bool = False
    # Patient-only tools are the mirror image of ``staff_only``: they are
    # hidden from staff sessions and fail closed for staff identities.
    patient_only: bool = False
    # Doctor-only tools are additionally hidden from admin/receptionist
    # sessions; ``authorize_tool_call`` enforces the same pin server-side.
    doctor_only: bool = False


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
        "(تاریخ جلالی). هر وقت بیمار روز مشخصی نام برد (مثل «شنبهٔ آینده» "
        "یا «فردا») باید همین Tool را برای دقیقاً همان روز صدا بزنی؛ اگر "
        "پزشک را نام نبرده است، اول پزشکان خدمت را با "
        "find_doctors_for_service بگیر و برای همان روز بررسی کن. برای "
        "روز مشخص هرگز find_nearest_appointments را جایگزین نکن.",
        FindAvailableSlotsInput,
        tools.find_available_slots,
    ),
    "find_nearest_appointments": ToolDefinition(
        "find_nearest_appointments",
        "read",
        "نزدیک‌ترین نوبت‌های واقعاً آزاد یک خدمت مشخص در ۳۰ روز آینده "
        "(پزشک، خدمت، تاریخ جلالی، ساعت). ابتدا service_id را از "
        "search_dental_services بگیر؛ تاریخ لازم نیست. فقط وقتی بیمار "
        "«نزدیک‌ترین» نوبت را می‌خواهد یا هیچ روز مشخصی نام نبرده است؛ "
        "برای روز مشخص از find_available_slots استفاده کن. اگر بیمار "
        "خدمت مشخصی نام نبرده است، برای «معاینه اولیه دندانپزشکی» "
        "(خدمت پیش‌فرض اولین مراجعه) صدا بزن و سؤال «چه خدمتی؟» نپرس.",
        FindNearestAppointmentsInput,
        tools.find_nearest_appointments,
    ),
    "get_patient_appointments": ToolDefinition(
        "get_patient_appointments",
        "read",
        "فهرست نوبت‌های بیمار مجاز با نام پزشک، نام خدمت، وضعیت، تاریخ و "
        "ساعت. شناسهٔ داخلی نوبت نمایش داده نمی‌شود. برای حساب بیمار، شناسه "
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
        "پیشنهاد لغو یک نوبت موجود. نوبت هدف را با مشخصات درخواست کاربر "
        "(پزشک، خدمت، تاریخ یا ساعت) و داده‌های دیتابیس سرور یکتا کن؛ "
        "شناسهٔ داخلی نوبت را از خروجی خواندنی نساز. اجرا فقط پس از "
        "تأیید معتبر کاربر.",
        CancelAppointmentInput,
        tools.cancel_appointment,
    ),
    "reschedule_appointment": ToolDefinition(
        "reschedule_appointment",
        "write",
        "پیشنهاد جابه‌جایی نوبت موجود به تاریخ و ساعت آزاد جدید. نوبت "
        "فعلی را با مشخصات درخواست کاربر و داده‌های دیتابیس سرور یکتا کن. "
        "ابتدا آزاد بودن Slot را بررسی کن؛ اجرا فقط پس از تأیید معتبر "
        "کاربر.",
        RescheduleAppointmentInput,
        tools.reschedule_appointment,
    ),
    "get_clinic_appointments_report": ToolDefinition(
        name="get_clinic_appointments_report",
        operation="read",
        description=(
            "آمار واقعی نوبت‌های کلینیک (امروز، بازهٔ پیش رو، لغوها و بار هر "
            "پزشک) فقط برای حساب‌های کارکنان. برای سؤال «چند نوبت پیش‌رو "
            "داریم» یا «برنامهٔ امروز» از همین Tool استفاده کن و به‌جای حدس، "
            "گزارش بساز. بیمارها اجازهٔ ندارند «همهٔ» نوبت‌های کلینیک را ببینند."
        ),
        input_schema=GetClinicAppointmentsReportInput,
        handler=tools.get_clinic_appointments_report,
        staff_only=True,
    ),
    "get_clinic_overview_stats": ToolDefinition(
        name="get_clinic_overview_stats",
        operation="read",
        description=(
            "نمای کلی کلینیک (تعداد بیمارها، پرونده‌های ناقص، پزشکان، خدمات و "
            "نوبت‌های آینده) فقط برای حساب مدیر. پیش از فراخوانی مطمئن شو "
            "جنس سؤال کل کلینیک است نه نوبت شخصی یک بیمار."
        ),
        input_schema=ClinicOverviewStatsInput,
        handler=tools.get_clinic_overview_stats,
        staff_only=True,
        admin_only=True,
    ),
    "search_patients": ToolDefinition(
        name="search_patients",
        operation="read",
        description=(
            "جست‌وجوی پروندهٔ بیماران (بخشی از نام، شماره تلفن یا کد ملی) "
            "فقط برای حساب‌های کارکنان؛ برای تماس با بیمار، پذیرش حضوری یا "
            "پیدا کردن patient_id برای ابزارهای بعدی. کد ملی در خروجی پوشانده "
            "شده است و هرگز کامل خوانده نمی‌شود."
        ),
        input_schema=SearchPatientsInput,
        handler=tools.search_patients,
        staff_only=True,
    ),
    "get_patient_summary": ToolDefinition(
        name="get_patient_summary",
        operation="read",
        description=(
            "کارت خلاصهٔ یک بیمار (نام، تلفن، وضعیت پرونده، تعداد نوبت‌های "
            "پیش‌رو، نوبت بعدی و ۵ مراجعهٔ اخیر) فقط برای حساب‌های کارکنان. "
            "patient_id را از search_patients یا get_doctor_day_plan بگیر."
        ),
        input_schema=PatientSummaryInput,
        handler=tools.get_patient_summary,
        staff_only=True,
    ),
    "get_patient_clinical_summary": ToolDefinition(
        name="get_patient_clinical_summary",
        operation="read",
        description=(
            "خلاصهٔ بالینی یک بیمار (حساسیت‌ها، یادداشت‌های درمانی اخیر، "
            "دندان‌های علامت‌خورده در چارت، ردیف‌های باز طرح درمان و آخرین "
            "نسخه) فقط برای حساب‌های کارکنان و پزشک. patient_id را از "
            "search_patients بگیر. حساب بیمار به این Tool دسترسی ندارد، "
            "حتی برای پروندهٔ خودش."
        ),
        input_schema=GetPatientClinicalSummaryInput,
        handler=tools.get_patient_clinical_summary,
        staff_only=True,
    ),
    "create_treatment_plan_draft": ToolDefinition(
        name="create_treatment_plan_draft",
        operation="write",
        description=(
            "پیشنهاد ثبت یک ردیف «پیش‌نویس» طرح درمان برای بیمار، فقط "
            "برای حساب پزشک. پیش‌نویس جزو برنامهٔ درمانی فعال بیمار نیست "
            "و هیچ‌وقت خودکار نهایی یا تأیید نمی‌شود. اجرا فقط پس از "
            "تأیید معتبر کاربر در رابط انجام می‌شود."
        ),
        input_schema=CreateTreatmentPlanDraftInput,
        handler=tools.create_treatment_plan_draft,
        staff_only=True,
        doctor_only=True,
    ),
    "get_doctor_schedules": ToolDefinition(
        name="get_doctor_schedules",
        operation="read",
        description=(
            "برنامهٔ هفتگی پزشکان فعال (روز هفته، ساعت کاری، طول هر Slot). "
            "برای «دکتر X چه روزهایی مطب دارد؟» یا پاسخ به این سؤال که "
            "چه روزهایی نوبت می‌دهند. برای همهٔ نقش‌ها از جمله بیماران "
            "قابل استفاده است."
        ),
        input_schema=GetDoctorSchedulesInput,
        handler=tools.get_doctor_schedules,
    ),
    "get_doctor_day_plan": ToolDefinition(
        name="get_doctor_day_plan",
        operation="read",
        description=(
            "برنامهٔ روزانهٔ یک پزشک در یک تاریخ جلالی مشخص (فهرست نوبت‌های "
            "آن روز با نام بیمار، خدمت، ساعت و وضعیت) فقط برای کارکنان. "
            "مدیر و پذیرش باید doctor_id بدهند؛ حساب پزشک همیشه به برنامهٔ "
            "خودش محدود می‌شود. برای مرور کار امروز یا پیدا کردن نوبت هدف "
            "برای لغو/جابه‌جایی استفاده کن."
        ),
        input_schema=GetDoctorDayPlanInput,
        handler=tools.get_doctor_day_plan,
        staff_only=True,
    ),
    "get_user_reports_summary": ToolDefinition(
        name="get_user_reports_summary",
        operation="read",
        description=(
            "خلاصهٔ بازخوردها و گزارش‌های ثبت‌شده کاربران (تعداد کل، تفکیک دسته و وضعیت، ۵ مورد "
            "اخیر) فقط برای حساب مدیر. برای «آیا بازخورد جدیدی داریم؟» یا "
            "مرور پیشنهادهای کاربران."
        ),
        input_schema=FeedbackSummaryInput,
        handler=tools.get_user_reports_summary,
        staff_only=True,
        admin_only=True,
    ),
    "get_my_profile": ToolDefinition(
        name="get_my_profile",
        operation="read",
        description=(
            "کارت پرونده‌های همین حساب بیمار (نام، تلفن، رابطه، وضعیت "
            "پرونده، تعداد نوبت‌های پیش‌رو و نوبت بعدی هر پرونده) فقط برای "
            "حساب‌های بیمار. برای «پروفایل من چیه؟» یا «چه پرونده‌هایی "
            "دارم؟» از همین Tool استفاده کن؛ کد ملی در خروجی نیست."
        ),
        input_schema=MyProfileInput,
        handler=tools.get_my_profile,
        patient_only=True,
    ),
    "create_patient": ToolDefinition(
        name="create_patient",
        operation="write",
        description=(
            "پیشنهاد ثبت پروندهٔ بیمار جدید (کد ملی، نام کامل، تلفن یکتا) "
            "توسط پذیرش/مدیر. اجرا فقط پس از تأیید معتبر کاربر در رابط "
            "انجام می‌شود؛ خطای تکراری‌بودن کد ملی یا تلفن را عیناً گزارش کن."
        ),
        input_schema=CreatePatientInput,
        handler=tools.create_patient,
        staff_only=True,
    ),
    "update_patient": ToolDefinition(
        name="update_patient",
        operation="write",
        description=(
            "پیشنهاد ویرایش پروندهٔ موجود (نام، تلفن یا کد ملی) توسط "
            "پذیرش/مدیر. فیلدهای ارسال‌نشده بدون تغییر می‌مانند؛ دست‌کم یک "
            "فیلد لازم است. اجرا فقط پس از تأیید معتبر کاربر."
        ),
        input_schema=UpdatePatientInput,
        handler=tools.update_patient,
        staff_only=True,
    ),
    "get_staff_directory": ToolDefinition(
        name="get_staff_directory",
        operation="read",
        description=(
            "فهرست و شمارش حساب‌های کاربران (تعداد هر نقش، فعال/غیرفعال، "
            "۵ حساب با آخرین ورود) فقط برای حساب مدیر. برای «چند حساب "
            "داریم؟» یا «چه کسی آخرین بار وارد شده؟» استفاده کن. رمز عبور "
            "هرگز در خروجی نیست."
        ),
        input_schema=StaffDirectoryInput,
        handler=tools.get_staff_directory,
        staff_only=True,
        admin_only=True,
    ),
    "get_audit_trail": ToolDefinition(
        name="get_audit_trail",
        operation="read",
        description=(
            "آخرین رخدادهای حساس ثبت‌شده در زنجیرهٔ audit (چه کسی، چه "
            "اقدامی، روی چه حسابی، چه زمانی) فقط برای حساب مدیر. برای "
            "«آخرین تغییرهای مدیریتی چه بوده؟» استفاده کن."
        ),
        input_schema=AuditTrailInput,
        handler=tools.get_audit_trail,
        staff_only=True,
        admin_only=True,
    ),
    "submit_feedback": ToolDefinition(
        name="submit_feedback",
        operation="write",
        description=(
            "پیشنهاد ثبت گزارش خطا یا پیشنهاد کاربر برای تیم پشتیبانی، "
            "برای همهٔ نقش‌ها. category فقط «error» یا «suggestion» است و "
            "متن را از خود کاربر بگیر. اجرا فقط پس از تأیید معتبر کاربر."
        ),
        input_schema=SubmitFeedbackInput,
        handler=tools.submit_feedback,
    ),
}


# Fields removed from patient-role calls before validation. Identity and the
# appointment target always come from the authenticated session and server-side
# database facts, never from a model/client-supplied id.
PATIENT_BOUND_FIELDS: dict[str, frozenset[str]] = {
    "book_appointment": frozenset(
        {"patient_id", "national_id", "full_name", "phone"}
    ),
    "get_patient_appointments": frozenset({"patient_id"}),
    "cancel_appointment": frozenset({"appointment_id"}),
    "reschedule_appointment": frozenset({"appointment_id"}),
}

# Tools whose input schema also receives the linked patient id from the server.
PATIENT_ID_INJECTED_TOOLS: frozenset[str] = frozenset(
    {"book_appointment", "get_patient_appointments"}
)


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
    role: str | None = None,
    actor: User | None = None,
) -> list[dict[str, object]]:
    """Return provider-neutral function schemas for the allowlisted tools.

    With ``patient_bound=True`` patient-identity fields are hidden from the
    model because the graph fills them from the authenticated patient account,
    patient-only tools become visible and staff/admin tools stay hidden.
    Staff-only tools stay hidden from patient sessions and admin-only tools
    are additionally hidden from receptionist/doctor sessions. Staff tools
    further follow the permission matrix: a role without the mapped action
    does not see the tool, while a per-account ``allow`` override (checked
    through ``actor``) makes it visible again. Hiding fields and tools is
    only a usability measure; server-side binding and ``authorize_tool_call``
    remain the security boundary.
    """
    schemas: list[dict[str, object]] = []
    for definition in TOOL_REGISTRY.values():
        if patient_bound:
            if definition.staff_only or definition.admin_only:
                # Clinic-wide reports and front-desk lookups are meaningless
                # and forbidden for patient accounts; not offering them keeps
                # the session honest. Server-side authorization remains the
                # real boundary in every case.
                continue
        else:
            if definition.patient_only:
                # Self-service profile tools exist only for patient sessions.
                continue
            if definition.admin_only and role != "admin":
                # Receptionist/doctor sessions never see admin-only tools.
                continue
            if definition.doctor_only and role != "doctor":
                # Only doctor sessions see doctor-only tools (e.g. treatment
                # plan drafts); admins use the panel for clinical writes.
                continue
            if definition.staff_only and not _staff_tool_visible(
                definition, role, actor
            ):
                # A role without the mapped action never sees the tool, so
                # the model cannot call something that would be denied.
                continue
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
