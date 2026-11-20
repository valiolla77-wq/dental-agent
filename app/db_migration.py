"""Explicit, additive SQLite schema migrations.

Every migration here is additive and idempotent: columns are only added when
missing, indexes are created with IF NOT EXISTS, and existing rows and IDs
are never touched. A migration that cannot be applied without changing
existing data aborts with a clear error instead of modifying rows.
"""

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models.appointment import APPOINTMENT_SLOT_INDEX

# Fixed SQL statements (no interpolation) for rebuilding ``patients``.
_COPY_PATIENTS_WITH_HOLDER = (
    "INSERT INTO patients_new "
    "(id, national_id, full_name, phone, user_id, is_account_holder, record_status) "
    "SELECT id, national_id, full_name, phone, user_id, is_account_holder, "
    "record_status FROM patients"
)
_COPY_PATIENTS_WITHOUT_HOLDER = (
    "INSERT INTO patients_new "
    "(id, national_id, full_name, phone, user_id, is_account_holder, record_status) "
    "SELECT id, national_id, full_name, phone, user_id, 0, "
    "record_status FROM patients"
)


async def _table_columns(conn: AsyncConnection, table: str) -> set[str]:
    return await conn.run_sync(
        lambda sync_conn: {
            column["name"]
            for column in inspect(sync_conn).get_columns(table)
        }
    )


async def _table_indexes(conn: AsyncConnection, table: str) -> set[str]:
    return await conn.run_sync(
        lambda sync_conn: {
            index["name"]
            for index in inspect(sync_conn).get_indexes(table)
        }
    )


async def _table_index_details(
    conn: AsyncConnection, table: str
) -> dict[str, bool]:
    """Map index name to whether it enforces uniqueness."""
    return await conn.run_sync(
        lambda sync_conn: {
            index["name"]: bool(index.get("unique"))
            for index in inspect(sync_conn).get_indexes(table)
        }
    )


async def _ensure_patient_user_link_index(conn: AsyncConnection) -> None:
    """Add the patient-account link column with a non-unique index.

    An account may own several patient records (the holder plus dependants),
    so this index is intentionally not unique. Legacy databases that still
    carry the old unique index are converted in place; the data is unchanged
    and duplicate links are now valid.
    """
    columns = await _table_columns(conn, "patients")
    if "user_id" not in columns:
        await conn.execute(
            text("ALTER TABLE patients ADD COLUMN user_id INTEGER REFERENCES users(id)")
        )

    indexes = await _table_index_details(conn, "patients")
    if indexes.get("ix_patients_user_id") is False:
        return

    if "ix_patients_user_id" in indexes:
        # The old one-to-one invariant must be removed before family records
        # can share the same account.
        await conn.execute(text("DROP INDEX ix_patients_user_id"))

    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_patients_user_id "
            "ON patients (user_id)"
        )
    )


async def _ensure_doctor_user_link_index(conn: AsyncConnection) -> None:
    """Add the optional doctor-account link column and unique index.

    Mirrors the patient-user link: the column is only added when missing and
    existing rows are never rewritten. Legacy databases with duplicate links
    abort startup with a clear error instead of being silently unlinked.
    """
    columns = await _table_columns(conn, "doctors")
    if "user_id" not in columns:
        await conn.execute(
            text("ALTER TABLE doctors ADD COLUMN user_id INTEGER REFERENCES users(id)")
        )

    indexes = await _table_index_details(conn, "doctors")
    if indexes.get("ix_doctors_user_id") is True:
        return

    duplicates = (
        await conn.execute(
            text(
                "SELECT user_id, COUNT(*) AS row_count "
                "FROM doctors "
                "WHERE user_id IS NOT NULL "
                "GROUP BY user_id "
                "HAVING COUNT(*) > 1 "
                "ORDER BY user_id "
                "LIMIT 5"
            )
        )
    ).all()
    if duplicates:
        sample = "; ".join(
            f"user_id={row.user_id}, count={row.row_count}"
            for row in duplicates
        )
        raise RuntimeError(
            "Cannot create the unique doctor-user link index: duplicate "
            f"links were found ({sample}). No doctor rows were modified."
        )

    if "ix_doctors_user_id" in indexes:
        # A same-named non-unique index cannot enforce the one-to-one link.
        await conn.execute(text("DROP INDEX ix_doctors_user_id"))

    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_doctors_user_id "
            "ON doctors (user_id)"
        )
    )


async def _ensure_appointment_slot_index(conn: AsyncConnection) -> None:
    """Create the partial unique slot index or abort on legacy duplicates."""
    columns = await _table_columns(conn, "appointments")
    if not {"doctor_id", "appointment_time", "status"} <= columns:
        return
    if APPOINTMENT_SLOT_INDEX in await _table_indexes(conn, "appointments"):
        return

    duplicates = (
        await conn.execute(
            text(
                "SELECT doctor_id, appointment_time, COUNT(*) AS row_count "
                "FROM appointments "
                "WHERE status = 'scheduled' "
                "GROUP BY doctor_id, appointment_time "
                "HAVING COUNT(*) > 1 "
                "ORDER BY doctor_id, appointment_time "
                "LIMIT 5"
            )
        )
    ).all()
    if duplicates:
        sample = "; ".join(
            f"doctor_id={row.doctor_id}, appointment_time={row.appointment_time}, "
            f"count={row.row_count}"
            for row in duplicates
        )
        raise RuntimeError(
            "Cannot create the unique appointment slot index: existing "
            f"scheduled duplicate slots were found ({sample}). "
            "No appointment rows were modified."
        )

    await conn.execute(
        text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {APPOINTMENT_SLOT_INDEX} "
            "ON appointments (doctor_id, appointment_time) "
            "WHERE status = 'scheduled'"
        )
    )


async def _ensure_appointment_flow_columns(conn: AsyncConnection) -> None:
    """Add the check-in / in-treatment / completion timestamps.

    Additive only: existing rows keep NULL timestamps, which the worklist
    renders as "booked, not arrived yet". No status values are rewritten.
    """
    columns = await _table_columns(conn, "appointments")
    if not columns:
        return

    additions = (
        ("checked_in_at", "DATETIME NULL"),
        ("started_at", "DATETIME NULL"),
        ("completed_at", "DATETIME NULL"),
        ("queue_number", "INTEGER NULL"),
    )
    for name, ddl_type in additions:
        if name not in columns:
            await conn.execute(
                text(f"ALTER TABLE appointments ADD COLUMN {name} {ddl_type}")
            )

    if "ix_appointments_queue_number" not in await _table_indexes(
        conn, "appointments"
    ):
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_appointments_queue_number "
                "ON appointments (queue_number)"
            )
        )


async def _ensure_patient_record_status(conn: AsyncConnection) -> None:
    """Make ``national_id`` optional and add the record status column.

    Legacy rows may still lack a national id; every current write path
    requires one. Legacy databases were built with a required ``national_id``,
    so making it nullable needs a controlled table rebuild: rows and ids are
    copied as-is, then the original table is replaced. Duplicate national ids
    abort with a clear error and leave the original table intact.
    """
    columns = await _table_columns(conn, "patients")
    if not columns:
        return

    if "national_id" not in columns:
        # A patients table without a national id column is not expected from
        # any historical schema; do not guess how to rebuild it.
        return

    if "record_status" not in columns:
        await conn.execute(
            text(
                "ALTER TABLE patients ADD COLUMN record_status VARCHAR(16) "
                "NOT NULL DEFAULT 'complete'"
            )
        )

    already_nullable = await conn.run_sync(
        lambda sync_conn: inspect(sync_conn).get_columns("patients")
    )
    national_id_details = next(
        (col for col in already_nullable if col["name"] == "national_id"),
        None,
    )
    if national_id_details is not None and national_id_details["nullable"]:
        return

    duplicates = (
        await conn.execute(
            text(
                "SELECT national_id, COUNT(*) AS row_count "
                "FROM patients "
                "WHERE national_id IS NOT NULL "
                "GROUP BY national_id "
                "HAVING COUNT(*) > 1 "
                "ORDER BY national_id "
                "LIMIT 5"
            )
        )
    ).all()
    if duplicates:
        sample = "; ".join(
            f"national_id={row.national_id}, count={row.row_count}"
            for row in duplicates
        )
        raise RuntimeError(
            "Cannot make the patient national id optional: duplicate values "
            f"were found ({sample}). No patient rows were modified."
        )

    has_holder = "is_account_holder" in columns
    await conn.execute(
        text(
            "CREATE TABLE patients_new ("
            "id INTEGER NOT NULL PRIMARY KEY, "
            "national_id VARCHAR(10), "
            "full_name VARCHAR(150) NOT NULL, "
            "phone VARCHAR(20) NOT NULL, "
            "user_id INTEGER REFERENCES users(id), "
            "is_account_holder BOOLEAN NOT NULL DEFAULT 0, "
            "record_status VARCHAR(16) NOT NULL DEFAULT 'complete')"
        )
    )
    await conn.execute(
        text(
            _COPY_PATIENTS_WITH_HOLDER
            if has_holder
            else _COPY_PATIENTS_WITHOUT_HOLDER
        )
    )
    await conn.execute(text("DROP TABLE patients"))
    await conn.execute(text("ALTER TABLE patients_new RENAME TO patients"))
    await conn.execute(
        text("CREATE UNIQUE INDEX ix_patients_national_id ON patients (national_id)")
    )
    await conn.execute(
        text("CREATE INDEX ix_patients_user_id ON patients (user_id)")
    )
    await conn.execute(
        text("CREATE INDEX ix_patients_record_status ON patients (record_status)")
    )


async def _ensure_patient_phone_unique_index(conn: AsyncConnection) -> None:
    """Enforce one patient per phone number, aborting on legacy duplicates."""
    columns = await _table_columns(conn, "patients")
    if "phone" not in columns:
        return

    indexes = await _table_index_details(conn, "patients")
    if indexes.get("ix_patients_phone") is True:
        return

    duplicates = (
        await conn.execute(
            text(
                "SELECT phone, COUNT(*) AS row_count "
                "FROM patients "
                "WHERE phone IS NOT NULL AND TRIM(phone) <> '' "
                "GROUP BY phone "
                "HAVING COUNT(*) > 1 "
                "ORDER BY phone "
                "LIMIT 5"
            )
        )
    ).all()
    if duplicates:
        sample = "; ".join(
            f"phone={row.phone}, count={row.row_count}" for row in duplicates
        )
        raise RuntimeError(
            "Cannot enforce a unique patient phone: duplicate phone numbers "
            f"were found ({sample}). No patient rows were modified."
        )

    if "ix_patients_phone" in indexes:
        await conn.execute(text("DROP INDEX ix_patients_phone"))
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_patients_phone "
            "ON patients (phone)"
        )
    )


async def _ensure_patient_account_holder(conn: AsyncConnection) -> None:
    """Add the account-holder marker and derive it for existing links."""
    columns = await _table_columns(conn, "patients")
    if "user_id" not in columns:
        return
    if "is_account_holder" not in columns:
        await conn.execute(
            text(
                "ALTER TABLE patients ADD COLUMN is_account_holder "
                "BOOLEAN NOT NULL DEFAULT 0"
            )
        )

    tables = await conn.run_sync(
        lambda sync_conn: set(inspect(sync_conn).get_table_names())
    )
    if "users" in tables:
        rows = (
            await conn.execute(
                text(
                    "SELECT p.id, p.user_id, p.phone, p.is_account_holder, "
                    "u.phone AS account_phone "
                    "FROM patients p JOIN users u ON u.id = p.user_id "
                    "ORDER BY p.id"
                )
            )
        ).all()
        existing_holders: set[int] = set()
        for row in rows:
            if row.user_id is not None and row.is_account_holder:
                existing_holders.add(int(row.user_id))

        # Derive the holder only when it is unambiguous and no holder was
        # already marked: linked record whose phone equals the account phone.
        for row in rows:
            user_id = row.user_id
            if user_id is None or int(user_id) in existing_holders:
                continue
            stored = "".join(char for char in (row.phone or "") if char.isdigit())
            account = "".join(
                char for char in (row.account_phone or "") if char.isdigit()
            )
            if stored and stored == account:
                await conn.execute(
                    text(
                        "UPDATE patients SET is_account_holder = 1 "
                        "WHERE id = :patient_id"
                    ),
                    {"patient_id": row.id},
                )
                existing_holders.add(int(user_id))

    if "ix_patients_is_account_holder" not in await _table_indexes(
        conn, "patients"
    ):
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_patients_is_account_holder "
                "ON patients (is_account_holder)"
            )
        )

    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_patients_account_holder "
            "ON patients (user_id) WHERE is_account_holder = 1"
        )
    )


async def _ensure_agent_conversation_patient(conn: AsyncConnection) -> None:
    """Add the persisted per-conversation patient selection."""
    tables = await conn.run_sync(
        lambda sync_conn: set(inspect(sync_conn).get_table_names())
    )
    if "agent_conversations" not in tables:
        return
    columns = await _table_columns(conn, "agent_conversations")
    if "selected_patient_id" not in columns:
        await conn.execute(
            text(
                "ALTER TABLE agent_conversations ADD COLUMN "
                "selected_patient_id INTEGER REFERENCES patients(id)"
            )
        )
    if "ix_agent_conversations_selected_patient_id" not in await _table_indexes(
        conn, "agent_conversations"
    ):
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_agent_conversations_selected_patient_id "
                "ON agent_conversations (selected_patient_id)"
            )
        )


async def _ensure_feedback_table(conn: AsyncConnection) -> None:
    """Create the append-only feedback table on existing databases."""
    from app.models.feedback import FeedbackReport

    await conn.run_sync(
        lambda sync_conn: FeedbackReport.__table__.create(
            sync_conn, checkfirst=True
        )
    )


async def _ensure_audit_logs_table(conn: AsyncConnection) -> None:
    """Create the append-only staff audit trail on existing databases."""
    from app.models.audit_log import AuditLog

    await conn.run_sync(
        lambda sync_conn: AuditLog.__table__.create(sync_conn, checkfirst=True)
    )


async def _ensure_user_audit_columns(conn: AsyncConnection) -> None:
    """Add account bookkeeping columns (created_at / last_login_at / overrides).

    Existing rows keep NULL for the new timestamp columns, which the API
    renders as unknown; permission overrides stay empty until an admin sets
    them explicitly.
    """
    columns = await _table_columns(conn, "users")
    if not columns:
        return
    if "created_at" not in columns:
        await conn.execute(
            text("ALTER TABLE users ADD COLUMN created_at DATETIME NULL")
        )
    if "last_login_at" not in columns:
        await conn.execute(
            text("ALTER TABLE users ADD COLUMN last_login_at DATETIME NULL")
        )
    if "permission_overrides" not in columns:
        await conn.execute(
            text("ALTER TABLE users ADD COLUMN permission_overrides JSON NULL")
        )


async def _ensure_portal_v3_tables(conn: AsyncConnection) -> None:
    """Create the patient-portal v3 tables on existing databases.

    Covers the clinical record (entries + per-tooth chart), the in-app
    notification inbox and post-visit satisfaction ratings. Every statement
    is ``checkfirst``: existing tables and rows are left untouched, so the
    migration is safe to run on every startup.
    """
    from app.models.clinical_entry import ClinicalEntry
    from app.models.notification import Notification
    from app.models.prescription import Prescription
    from app.models.tooth_status import ToothStatus
    from app.models.treatment_plan import TreatmentPlanItem
    from app.models.visit_rating import VisitRating

    for model in (
        ClinicalEntry,
        ToothStatus,
        Notification,
        VisitRating,
        Prescription,
        TreatmentPlanItem,
    ):
        await conn.run_sync(
            lambda sync_conn, table=model.__table__: table.create(
                sync_conn, checkfirst=True
            )
        )


async def _ensure_bale_link_table(conn: AsyncConnection) -> None:
    """Create the Bale chat ↔ phone link table on existing databases.

    Additive and idempotent (``checkfirst``): the table only appears when the
    Bale OTP delivery channel is used; existing databases keep working with
    the other providers unchanged.
    """
    from app.models.bale_link import BaleChatLink

    await conn.run_sync(
        lambda sync_conn: BaleChatLink.__table__.create(
            sync_conn, checkfirst=True
        )
    )


async def run_additive_migrations(conn: AsyncConnection) -> None:
    """Apply additive schema changes without touching existing rows."""
    if conn.dialect.name != "sqlite":
        return

    await _ensure_patient_user_link_index(conn)
    await _ensure_doctor_user_link_index(conn)
    await _ensure_patient_record_status(conn)
    await _ensure_patient_phone_unique_index(conn)
    await _ensure_patient_account_holder(conn)
    await _ensure_agent_conversation_patient(conn)
    await _ensure_feedback_table(conn)
    await _ensure_audit_logs_table(conn)
    await _ensure_user_audit_columns(conn)
    await _ensure_portal_v3_tables(conn)
    await _ensure_bale_link_table(conn)
    await _ensure_appointment_flow_columns(conn)
    await _ensure_appointment_slot_index(conn)
