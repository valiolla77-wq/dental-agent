"""Patient domain operations and persistence.

Registration model:

- A phone number belongs to exactly one patient record.
- A patient account may own several patient records: one account-holder record
  (``is_account_holder=True``) plus any number of family/dependent records.
- National id is mandatory for every current registration path. Legacy rows
  without one remain readable but are reported as ``incomplete``.
- The record status is always re-derived from stored fields; no request payload
  can set it directly.
"""

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models.appointment import Appointment
from app.models.chat import AgentConversation
from app.models.patient import Patient

STATUS_COMPLETE = "complete"
STATUS_INCOMPLETE = "incomplete"
_RECORD_STATUSES = (STATUS_COMPLETE, STATUS_INCOMPLETE)

# Persian/Arabic digit input for national ids and phones is normalized to
# ASCII digits before any match or write.
_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"
)


def normalize_national_id(value: str | None) -> str:
    """Return only ASCII digits of the input (empty string when no digits)."""
    if value is None:
        return ""
    return "".join(
        char for char in str(value).translate(_DIGIT_TRANSLATION) if char.isdigit()
    )


def normalize_phone(value: str | None) -> str:
    """Return digits-only phone, or raise the catalogued validation error."""
    digits = "".join(
        char for char in str(value or "").translate(_DIGIT_TRANSLATION)
        if char.isdigit()
    )
    if not 8 <= len(digits) <= 15:
        raise AppError("COMMON_VALIDATION_ERROR")
    return digits


def _validated_national_id(value: str | None) -> str:
    """Normalized mandatory national id, or the catalogued validation error."""
    digits = normalize_national_id(value)
    if len(digits) != 10:
        raise AppError("COMMON_VALIDATION_ERROR")
    return digits


def _derived_status(patient: Patient) -> str:
    """Record status is a pure function of the stored required fields."""
    return STATUS_COMPLETE if patient.national_id else STATUS_INCOMPLETE


async def get_patient_by_national_id(
    db: AsyncSession,
    national_id: str,
) -> Patient | None:
    result = await db.execute(
        select(Patient).where(Patient.national_id == national_id)
    )
    return result.scalar_one_or_none()


async def get_patient_by_phone(
    db: AsyncSession,
    phone: str,
) -> Patient | None:
    result = await db.execute(
        select(Patient).where(Patient.phone == phone)
    )
    return result.scalar_one_or_none()


async def get_patients_by_user_id(
    db: AsyncSession,
    user_id: int,
) -> list[Patient]:
    """Return every patient record owned by an account, primary first."""
    result = await db.execute(
        select(Patient)
        .where(Patient.user_id == user_id)
        .order_by(Patient.is_account_holder.desc(), Patient.id)
    )
    return list(result.scalars().all())


async def get_patient_by_user_id(
    db: AsyncSession,
    user_id: int,
) -> Patient | None:
    """Return the primary linked record (holder first), if any.

    Kept for callers that only need a default single patient. New code that
    offers a patient choice must use :func:`get_patients_by_user_id`.
    """
    patients = await get_patients_by_user_id(db, user_id)
    return patients[0] if patients else None


async def create_patient(
    db: AsyncSession,
    national_id: str,
    full_name: str,
    phone: str,
    *,
    commit: bool = True,
    record_status: str = STATUS_COMPLETE,
) -> Patient:
    """Staff-registered record: national id and unique phone are required."""
    national_id = _validated_national_id(national_id)
    phone = normalize_phone(phone)
    if record_status not in _RECORD_STATUSES:
        raise AppError("COMMON_VALIDATION_ERROR")

    existing_patient = await get_patient_by_national_id(db, national_id)
    if existing_patient is not None:
        raise AppError("PATIENT_DUPLICATE_NATIONAL_ID")
    existing_phone = await get_patient_by_phone(db, phone)
    if existing_phone is not None:
        raise AppError("PATIENT_DUPLICATE_PHONE")

    new_patient = Patient(
        national_id=national_id,
        full_name=full_name.strip(),
        phone=phone,
        record_status=STATUS_COMPLETE,
        is_account_holder=False,
    )
    db.add(new_patient)

    if commit:
        try:
            await db.commit()
        except IntegrityError:
            # Unique indexes are the final authority under concurrency.
            await db.rollback()
            raise await _registration_conflict(db, national_id, phone) from None
        await db.refresh(new_patient)
    else:
        await db.flush()
    return new_patient


async def _registration_conflict(
    db: AsyncSession,
    national_id: str,
    phone: str,
) -> AppError:
    """Map a uniqueness violation to the most specific catalogued error."""
    if await get_patient_by_national_id(db, national_id) is not None:
        return AppError("PATIENT_DUPLICATE_NATIONAL_ID")
    if await get_patient_by_phone(db, phone) is not None:
        return AppError("PATIENT_DUPLICATE_PHONE")
    return AppError("COMMON_CONFLICT")


async def create_initial_record(
    db: AsyncSession,
    *,
    user_id: int,
    full_name: str,
    phone: str,
    national_id: str,
    relation: str,
    account_phone: str,
) -> Patient:
    """Register a patient under an authenticated patient account.

    ``relation="self"`` requires the submitted phone to equal the account
    phone and creates/updates the single account-holder record. ``other`` is a
    family/dependent record with its own unique phone. A matching unlinked
    reception-created record with the same national id and phone may be
    adopted instead of duplicated.
    """
    if relation not in ("self", "other"):
        raise AppError("COMMON_VALIDATION_ERROR")

    national_id = _validated_national_id(national_id)
    phone = normalize_phone(phone)
    own_phone = normalize_phone(account_phone)

    if relation == "self" and phone != own_phone:
        raise AppError("COMMON_VALIDATION_ERROR")
    if relation == "other" and phone == own_phone:
        raise AppError("COMMON_VALIDATION_ERROR")

    owned = await get_patients_by_user_id(db, user_id)
    if relation == "self" and any(
        patient.is_account_holder or patient.phone == own_phone
        for patient in owned
    ):
        # The account holder is already registered; use relation="other" for
        # family members. Do not silently create a second self record.
        raise AppError("COMMON_CONFLICT")

    candidate = await get_patient_by_national_id(db, national_id)
    if candidate is not None:
        if candidate.user_id not in (None, user_id):
            raise AppError("PATIENT_DUPLICATE_NATIONAL_ID")
        if candidate.phone != phone:
            raise AppError("PATIENT_DUPLICATE_NATIONAL_ID")
        if candidate.user_id == user_id:
            raise AppError("COMMON_CONFLICT")
        patient = candidate
        patient.user_id = user_id
        patient.full_name = full_name.strip()
        patient.is_account_holder = relation == "self"
        patient.record_status = STATUS_COMPLETE
    else:
        existing_phone = await get_patient_by_phone(db, phone)
        if existing_phone is not None:
            raise AppError("PATIENT_DUPLICATE_PHONE")
        patient = Patient(
            national_id=national_id,
            full_name=full_name.strip(),
            phone=phone,
            user_id=user_id,
            is_account_holder=relation == "self",
            record_status=STATUS_COMPLETE,
        )
        db.add(patient)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise await _registration_conflict(db, national_id, phone) from None
    await db.refresh(patient)
    return patient


async def list_patients(
    db: AsyncSession,
    *,
    search: str | None = None,
    record_status: str | None = None,
) -> list[Patient]:
    """List patient records, optionally filtered by an authorized search term."""
    if record_status is not None and record_status not in _RECORD_STATUSES:
        raise AppError("COMMON_VALIDATION_ERROR")
    query = select(Patient).order_by(Patient.id)
    if record_status is not None:
        query = query.where(Patient.record_status == record_status)
    term = (search or "").strip()
    if term:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.where(
            Patient.full_name.ilike(pattern, escape="\\")
            | Patient.phone.ilike(pattern, escape="\\")
            | Patient.national_id.ilike(pattern, escape="\\")
        )
    result = await db.execute(query.limit(200))
    return list(result.scalars().all())


async def get_patient(db: AsyncSession, patient_id: int) -> Patient:
    result = await db.execute(
        select(Patient).where(Patient.id == patient_id)
    )
    patient = result.scalar_one_or_none()

    if patient is None:
        raise AppError("PATIENT_NOT_FOUND")

    return patient


async def update_patient(
    db: AsyncSession,
    patient_id: int,
    full_name: str,
    phone: str,
    national_id: str | None = None,
) -> Patient:
    """Staff edit of a record; ``record_status`` is re-derived afterwards.

    ``national_id`` is optional here only to allow staff to keep working on a
    legacy incomplete row. New registrations always require it.
    """
    patient = await get_patient(db, patient_id)
    normalized_phone = normalize_phone(phone)
    duplicate_phone = await get_patient_by_phone(db, normalized_phone)
    if duplicate_phone is not None and duplicate_phone.id != patient.id:
        raise AppError("PATIENT_DUPLICATE_PHONE")

    patient.full_name = full_name.strip()
    patient.phone = normalized_phone

    if national_id is not None:
        digits = _validated_national_id(national_id)
        duplicate = await get_patient_by_national_id(db, digits)
        if duplicate is not None and duplicate.id != patient.id:
            raise AppError("PATIENT_DUPLICATE_NATIONAL_ID")
        patient.national_id = digits

    patient.record_status = _derived_status(patient)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise await _registration_conflict(
            db, patient.national_id or "", normalized_phone
        ) from None
    await db.refresh(patient)
    return patient


async def delete_patient(db: AsyncSession, patient_id: int) -> int:
    """Permanently remove a patient record and its appointment history.

    Guarded against accidental data loss: a record with scheduled (active)
    appointments must first have them cancelled, so an admin can never wipe
    upcoming clinic visits by mistake. Historical (cancelled/completed)
    appointments are removed with the record instead of being orphaned.
    """
    patient = await get_patient(db, patient_id)

    active_count = await db.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(
            Appointment.patient_id == patient_id,
            Appointment.status == "scheduled",
        )
    )
    if active_count:
        raise AppError("PATIENT_HAS_ACTIVE_APPOINTMENTS")

    # Detach the conversation pointer (nullable FK) so past chats stay usable
    # without dangling references.
    await db.execute(
        AgentConversation.__table__.update()
        .where(AgentConversation.selected_patient_id == patient_id)
        .values(selected_patient_id=None)
    )
    await db.execute(
        delete(Appointment).where(Appointment.patient_id == patient_id)
    )
    await db.delete(patient)
    await db.commit()
    return patient_id
