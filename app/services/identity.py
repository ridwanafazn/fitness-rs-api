"""Identity, profile, equipment, injury, and consent services."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import (
    ConflictError,
    ConsentRequiredError,
    ProfileValidationError,
    UnknownInjuryError,
)
from app.db.models import Consent, Profile, User, UserEquipment, UserInjury
from app.domain.constants import (
    EQUIPMENT_VALUES,
    Equipment,
    is_valid_injury_term,
    normalise_injury_token,
    normalise_token,
    supported_injury_terms,
)
from app.domain.injuries import map_injury_to_body_parts
from app.domain.profile import (
    EQUIPMENT_ALIASES,
    PROFILE_REQUIRED_FIELDS,
    ConsentKind,
)
from app.services.audit import record_audit


def utcnow() -> datetime:
    return datetime.now(UTC)


def commit_or_conflict(session: Session) -> None:
    """Commit, translating a unique-constraint race into a 409."""

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("Data berubah secara bersamaan. Coba lagi.") from exc


def normalise_equipment(values: Iterable[str]) -> List[Equipment]:
    normalised: List[Equipment] = []
    unknown: List[str] = []
    seen: set[str] = set()

    for raw in values:
        if not isinstance(raw, str):
            raise ProfileValidationError("Equipment hanya boleh berisi string.")
        token = normalise_token(raw)
        token = EQUIPMENT_ALIASES.get(token, token)
        try:
            equipment = Equipment(token)
        except ValueError:
            unknown.append(raw)
            continue
        if equipment.value not in seen:
            seen.add(equipment.value)
            normalised.append(equipment)

    if unknown:
        raise ProfileValidationError(
            "Equipment tidak dikenali.",
            details={
                "unknown_equipment": unknown,
                "supported": list(EQUIPMENT_VALUES),
            },
        )
    return normalised


def normalise_injuries(values: Iterable[str]) -> List[Tuple[str, List[str]]]:
    terms: List[str] = []
    unknown: List[str] = []
    seen: set[str] = set()

    for raw in values:
        if not isinstance(raw, str):
            raise ProfileValidationError("Cedera hanya boleh berisi string.")
        term = normalise_injury_token(raw)
        if not term:
            continue
        if len(term) > 60:
            raise ProfileValidationError("Nama cedera terlalu panjang.")
        if not is_valid_injury_term(term):
            unknown.append(term)
            continue
        if term not in seen:
            seen.add(term)
            terms.append(term)

    if unknown:
        examples = ", ".join(sorted(supported_injury_terms())[:20])
        raise UnknownInjuryError(
            f"Nama cedera tidak dikenali: {', '.join(unknown)}.",
            details={
                "unknown_terms": unknown,
                "supported_examples": examples,
                "hint": (
                    "Gunakan body part (chest, back, shoulders), nama otot "
                    "(pectoralis major), atau istilah umum (knee, lower back, "
                    "elbow, wrist)."
                ),
            },
        )

    result: List[Tuple[str, List[str]]] = []
    for term in terms:
        parts = sorted(part.value for part in map_injury_to_body_parts([term]))
        result.append((term, parts))
    return result


def latest_consents(session: Session, user_id: uuid.UUID) -> List[Consent]:
    return list(
        session.scalars(
            select(Consent)
            .where(Consent.user_id == user_id)
            .order_by(Consent.granted_at.desc(), Consent.created_at.desc())
        ).all()
    )


def active_consent_map(session: Session, user_id: uuid.UUID) -> Dict[ConsentKind, Consent]:
    latest: Dict[ConsentKind, Consent] = {}
    for row in latest_consents(session, user_id):
        kind = ConsentKind(row.kind)
        latest.setdefault(kind, row)
    return {kind: row for kind, row in latest.items() if row.revoked_at is None}


def consent_status(session: Session, user_id: uuid.UUID) -> Dict[str, bool]:
    active = active_consent_map(session, user_id)
    return {kind.value: kind in active for kind in ConsentKind}


def has_active_consent(session: Session, user_id: uuid.UUID, kind: ConsentKind) -> bool:
    return kind in active_consent_map(session, user_id)


def profile_is_complete(profile: Optional[Profile]) -> bool:
    if profile is None:
        return False
    return all(getattr(profile, field) is not None for field in PROFILE_REQUIRED_FIELDS)


def upsert_profile(
    session: Session,
    user_id: uuid.UUID,
    data: Dict[str, Any],
    *,
    partial: bool,
) -> Profile:
    profile = session.get(Profile, user_id)
    if profile is None:
        profile = Profile(user_id=user_id)
        session.add(profile)

    for field, value in data.items():
        if field not in PROFILE_REQUIRED_FIELDS or value is None:
            continue
        setattr(profile, field, value)

    profile.updated_at = utcnow()
    session.flush()
    return profile


def replace_equipment(session: Session, user_id: uuid.UUID, values: Iterable[str]) -> List[str]:
    normalised = normalise_equipment(values)
    session.execute(delete(UserEquipment).where(UserEquipment.user_id == user_id))
    session.add_all(
        UserEquipment(user_id=user_id, equipment=equipment.value) for equipment in normalised
    )
    session.flush()
    return [equipment.value for equipment in normalised]


def replace_injuries(
    session: Session,
    user_id: uuid.UUID,
    values: Iterable[str],
    *,
    require_consent: bool = True,
) -> List[UserInjury]:
    normalised = normalise_injuries(values)
    if (
        normalised
        and require_consent
        and not has_active_consent(session, user_id, ConsentKind.HEALTH_DATA_PROCESSING)
    ):
        raise ConsentRequiredError()

    session.execute(delete(UserInjury).where(UserInjury.user_id == user_id))
    injuries = [
        UserInjury(user_id=user_id, term=term, body_parts=body_parts)
        for term, body_parts in normalised
    ]
    session.add_all(injuries)
    session.flush()
    return injuries


def _injury_count(session: Session, user_id: uuid.UUID) -> int:
    count = session.scalar(
        select(func.count()).select_from(UserInjury).where(UserInjury.user_id == user_id)
    )
    return int(count or 0)


def apply_consents(
    session: Session,
    *,
    user_id: uuid.UUID,
    actor_role: str,
    updates: Dict[ConsentKind, bool],
    policy_version: str,
) -> Dict[str, bool]:
    """Grant/revoke consents and return the resulting active state.

    Revoking health-data consent deletes stored injuries immediately: keeping
    health data after consent is withdrawn is not a defensible default.
    """

    current = active_consent_map(session, user_id)
    now = utcnow()
    changed = False

    for kind, granted in updates.items():
        active = current.get(kind)

        if granted:
            if active is None:
                session.add(
                    Consent(
                        user_id=user_id,
                        kind=kind.value,
                        version=policy_version,
                        granted_at=now,
                    )
                )
                record_audit(
                    session,
                    actor_user_id=user_id,
                    actor_role=actor_role,
                    action="consent.granted",
                    resource_type="consent",
                    resource_id=kind.value,
                    metadata={"kind": kind.value, "version": policy_version},
                )
                changed = True
            elif active.version != policy_version:
                active.revoked_at = now
                record_audit(
                    session,
                    actor_user_id=user_id,
                    actor_role=actor_role,
                    action="consent.revoked",
                    resource_type="consent",
                    resource_id=kind.value,
                    metadata={
                        "kind": kind.value,
                        "version": active.version,
                        "reason": "policy_version_changed",
                    },
                )
                session.add(
                    Consent(
                        user_id=user_id,
                        kind=kind.value,
                        version=policy_version,
                        granted_at=now,
                    )
                )
                record_audit(
                    session,
                    actor_user_id=user_id,
                    actor_role=actor_role,
                    action="consent.granted",
                    resource_type="consent",
                    resource_id=kind.value,
                    metadata={"kind": kind.value, "version": policy_version},
                )
                changed = True
        elif active is not None:
            active.revoked_at = now
            record_audit(
                session,
                actor_user_id=user_id,
                actor_role=actor_role,
                action="consent.revoked",
                resource_type="consent",
                resource_id=kind.value,
                metadata={"kind": kind.value, "version": active.version},
            )
            changed = True

            if kind is ConsentKind.HEALTH_DATA_PROCESSING:
                count = _injury_count(session, user_id)
                if count:
                    session.execute(delete(UserInjury).where(UserInjury.user_id == user_id))
                    record_audit(
                        session,
                        actor_user_id=user_id,
                        actor_role=actor_role,
                        action="profile.injuries_cleared",
                        resource_type="user",
                        resource_id=str(user_id),
                        metadata={"count": count, "reason": "consent_revoked"},
                    )

    if changed:
        session.flush()
    return consent_status(session, user_id)


def request_account_deletion(
    session: Session,
    *,
    user: User,
    actor_role: str,
    grace_days: int,
) -> Tuple[datetime, datetime, uuid.UUID]:
    now = utcnow()
    scheduled_for = now + timedelta(days=grace_days)
    user.deletion_requested_at = now
    user.deletion_scheduled_for = scheduled_for

    entry = record_audit(
        session,
        actor_user_id=user.id,
        actor_role=actor_role,
        action="account.deletion_requested",
        resource_type="user",
        resource_id=str(user.id),
        metadata={"scheduled_for": scheduled_for.isoformat()},
    )
    session.flush()
    return now, scheduled_for, entry.id
