"""Dental service domain operations and persistence."""

import difflib

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models.appointment import Appointment
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_dental_service import doctor_dental_services
from app.utils.persian_text import (
    GENERIC_SEARCH_TERMS,
    canonicalize_token,
    concept_aliases,
    normalize_persian_text,
    search_terms,
)


async def create_dental_service(
    db: AsyncSession,
    name: str,
    description: str | None = None,
) -> DentalService:
    dental_service = DentalService(name=name, description=description)
    db.add(dental_service)
    await db.commit()
    await db.refresh(dental_service)
    return dental_service


async def list_dental_services(
    db: AsyncSession,
    active_only: bool = True,
) -> list[DentalService]:
    query = select(DentalService)
    if active_only:
        query = query.where(DentalService.is_active.is_(True))
    result = await db.execute(
        query.order_by(DentalService.id)
    )
    return list(result.scalars().all())


def _canonical_tokens(value: str | None) -> set[str]:
    return {
        canonicalize_token(token)
        for token in normalize_persian_text(value).split()
        if token
    }


def _relevance_score(
    service: DentalService,
    terms: list[str],
    *,
    normalized_query: str,
) -> float:
    """Score a service against query terms using name-first lexical ranking."""
    name_text = normalize_persian_text(service.name)
    description_text = normalize_persian_text(service.description)
    name_tokens = _canonical_tokens(service.name)
    description_tokens = _canonical_tokens(service.description)
    name_aliases = concept_aliases(name_tokens)
    description_aliases = concept_aliases(description_tokens)
    known_tokens = name_tokens | description_tokens | name_aliases | description_aliases

    damage_only = bool({"خراب", "شکسته"} & set(terms))
    has_specific_query_term = any(
        term not in GENERIC_SEARCH_TERMS for term in terms
    )
    score = 0.0
    matched_terms = 0
    specific_terms: list[str] = []
    for term in terms:
        # Resolve a small spelling variation to catalog vocabulary first, so
        # the typo receives the same name/description/alias weighting as the
        # intended word instead of an arbitrary tie-breaker.
        effective_term = term
        if term not in known_tokens and len(term) >= 4:
            close = difflib.get_close_matches(
                term,
                sorted(known_tokens),
                n=1,
                cutoff=0.86,
            )
            if close and close[0] not in GENERIC_SEARCH_TERMS:
                effective_term = close[0]

        matched = False
        term_score = 0.0
        if effective_term in name_tokens:
            term_score += 5.0
            matched = True

        if effective_term in description_tokens:
            term_score += 2.0
            matched = True

        if effective_term in name_aliases:
            term_score += 3.0
            matched = True
        if effective_term in description_aliases:
            term_score += 1.5
            matched = True

        if not matched:
            continue

        # Generic tooth/browse words support candidates when the query has
        # specific wording, but do not manufacture relevance for a generic
        # catalog browse; that path is handled deterministically by caller.
        if effective_term in GENERIC_SEARCH_TERMS and not (
            has_specific_query_term or damage_only or matched_terms
        ):
            continue

        matched_terms += 1
        score += term_score
        if effective_term not in GENERIC_SEARCH_TERMS:
            specific_terms.append(term)

    if not matched_terms:
        return 0.0

    # For "پوسیدگی دندان" or "درد دندان", matching only "دندان" is not
    # enough to recommend a service such as bleaching.
    if has_specific_query_term and not specific_terms:
        return 0.0

    # Prefer services covering more of the patient's wording.
    score += 3.0 * (matched_terms / len(terms))

    # A complete phrase match is stronger than scattered token matches.
    if normalized_query:
        if normalized_query in name_text:
            score += 4.0
        if normalized_query in description_text:
            score += 2.0

    # "خراب"/"شکسته" describe damage, not necessarily caries. Keep those
    # candidates selectable but rank them below explicit caries wording so
    # the agent can ask a clarifying question instead of choosing silently.
    if damage_only and not ({"پوسیدگی", "ترمیم"} & set(terms)):
        score *= 0.75
    return score


async def search_dental_services(
    db: AsyncSession,
    name_query: str | None = None,
    *,
    limit: int = 20,
) -> list[DentalService]:
    """Return active services ranked by Persian name/description relevance.

    The catalog is deliberately loaded and ranked in Python: a clinic's
    service list is small, while normalized multi-word matching is not
    expressible reliably with SQLite ``LIKE``. Stored text is never modified.
    A blank/generic query lists active services; an unmatched query returns an
    empty list instead of unrelated fallback results.
    """
    limit = max(1, min(int(limit), 50))
    result = await db.execute(
        select(DentalService)
        .where(DentalService.is_active.is_(True))
        .order_by(DentalService.id)
    )
    services = list(result.scalars().all())
    normalized_query = normalize_persian_text(name_query)
    if not normalized_query:
        return services[:limit]

    terms = search_terms(name_query)
    if not terms:
        # Explicit generic browsing (for example "خدمات مطب") is deterministic:
        # return active services in catalog order, bounded by limit.
        return services[:limit]

    # Context-only phrases such as "فقط دندون" or "دندان" remain browsable,
    # but generic words never earn a relevance score over unrelated services.
    if not any(term not in GENERIC_SEARCH_TERMS for term in terms) or all(
        term in GENERIC_SEARCH_TERMS or term == "فقط" for term in terms
    ):
        # Generic browsing is deterministic, but a query containing the
        # focus word "فقط" still narrows to common examination/repair
        # choices instead of presenting unrelated cleaning/whitening rows.
        if any(term == "فقط" for term in terms):
            focused_only = [
                service
                for service in services
                if {"معاینه", "بررسی", "ترمیم"}
                & _canonical_tokens(service.name)
            ]
            if focused_only:
                return focused_only[:limit]
        return services[:limit]

    # Damage wording is deliberately broad: without a diagnostic leap, show
    # the active examination/filling choices in catalog order for a focused
    # clarification instead of ranking plaque cleaning or whitening first.
    if {"خراب", "شکسته"} & set(terms) and not (
        {"پوسیدگی", "درد", "ترمیم"} & set(terms)
    ):
        focused = {
            canonicalize_token(service.name)
            for service in services
            if {"معاینه", "بررسی", "ترمیم"} & _canonical_tokens(service.name)
        }
        selected = [
            service
            for service in services
            if focused & _canonical_tokens(service.name)
        ]
        if selected:
            return selected[:limit]

    scored: list[tuple[float, DentalService]] = []
    for service in services:
        score = _relevance_score(
            service,
            terms,
            normalized_query=normalized_query,
        )
        if score > 0:
            scored.append((score, service))

    if not scored:
        return []

    scored.sort(key=lambda item: (-item[0], item[1].id))
    return [service for _, service in scored[:limit]]


async def get_dental_service(
    db: AsyncSession,
    service_id: int,
) -> DentalService:
    dental_service = await db.get(DentalService, service_id)
    if dental_service is None:
        raise AppError("DENTAL_SERVICE_NOT_FOUND")
    return dental_service


async def update_dental_service(
    db: AsyncSession,
    service_id: int,
    name: str,
    description: str | None,
    is_active: bool,
) -> DentalService:
    dental_service = await get_dental_service(db, service_id)
    dental_service.name = name
    dental_service.description = description
    dental_service.is_active = is_active
    await db.commit()
    await db.refresh(dental_service)
    return dental_service


async def delete_dental_service(db: AsyncSession, service_id: int) -> int:
    dental_service = await get_dental_service(db, service_id)
    appointment_count = await db.scalar(
        select(func.count(Appointment.id)).where(
            Appointment.service_id == service_id
        )
    )
    if appointment_count:
        raise AppError("DENTAL_SERVICE_IN_USE")

    await db.delete(dental_service)
    await db.commit()
    return service_id


async def get_doctor_services(
    db: AsyncSession,
    doctor_id: int,
) -> list[DentalService]:
    doctor = await db.get(Doctor, doctor_id)
    if doctor is None:
        raise AppError("DOCTOR_NOT_FOUND")

    result = await db.execute(
        select(DentalService)
        .join(doctor_dental_services)
        .where(doctor_dental_services.c.doctor_id == doctor_id)
        .order_by(DentalService.id)
    )
    return list(result.scalars().all())


async def get_service_doctors(
    db: AsyncSession,
    service_id: int,
) -> list[Doctor]:
    dental_service = await get_dental_service(db, service_id)
    if not dental_service.is_active:
        return []
    result = await db.execute(
        select(Doctor)
        .join(doctor_dental_services)
        .where(
            doctor_dental_services.c.dental_service_id == service_id,
            Doctor.is_active.is_(True),
        )
        .order_by(Doctor.id)
    )
    return list(result.scalars().all())


async def set_doctor_services(
    db: AsyncSession,
    doctor: Doctor,
    service_ids: list[int],
) -> None:
    unique_ids = list(dict.fromkeys(service_ids))
    if not unique_ids:
        doctor.dental_services = []
        return

    result = await db.execute(
        select(DentalService).where(DentalService.id.in_(unique_ids))
    )
    services_by_id = {service.id: service for service in result.scalars().all()}
    missing_ids = [service_id for service_id in unique_ids if service_id not in services_by_id]
    if missing_ids:
        raise AppError("DENTAL_SERVICE_NOT_FOUND", {"service_ids": missing_ids})

    doctor.dental_services = [services_by_id[service_id] for service_id in unique_ids]
