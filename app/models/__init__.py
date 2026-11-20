from app.models.agent_confirmation import AgentConfirmation
from app.models.appointment import Appointment
from app.models.audit_log import AuditLog
from app.models.bale_link import BaleChatLink
from app.models.chat import AgentConversation, AgentMessage
from app.models.clinical_entry import ClinicalEntry
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_schedule import DoctorSchedule
from app.models.feedback import FeedbackReport
from app.models.notification import Notification
from app.models.otp import OtpCode
from app.models.patient import Patient
from app.models.prescription import Prescription
from app.models.tooth_status import ToothStatus
from app.models.treatment_plan import TreatmentPlanItem
from app.models.user import User
from app.models.visit_rating import VisitRating

# Importing the models registers every table on ``Base.metadata``.
__all__ = [
    "AgentConfirmation",
    "AgentConversation",
    "AgentMessage",
    "Appointment",
    "AuditLog",
    "BaleChatLink",
    "ClinicalEntry",
    "DentalService",
    "Doctor",
    "DoctorSchedule",
    "FeedbackReport",
    "Notification",
    "OtpCode",
    "Patient",
    "Prescription",
    "ToothStatus",
    "TreatmentPlanItem",
    "User",
    "VisitRating",
]
