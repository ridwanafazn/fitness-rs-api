"""P0.1 identity, profile, equipment, injury, consent, and export endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_settings
from app.auth.dependencies import Principal, get_current_principal, get_db_session
from app.core.config import Settings
from app.core.errors import ConflictError, ConsentRequiredError
from app.db.models import Profile, User, UserEquipment, UserInjury
from app.domain.profile import ConsentKind
from app.schemas.me import (
    ConsentRecordOut,
    ConsentStateResponse,
    ConsentUpdate,
    DeletionResponse,
    EquipmentResponse,
    EquipmentUpdate,
    ExportResponse,
    InjuryOut,
    InjuryResponse,
    InjuryUpdate,
    MeResponse,
    MeUser,
    OnboardingRequest,
    ProfileOut,
    ProfilePatch,
    ProfileResponse,
)
from app.schemas.recommendation import ErrorResponse
from app.services.audit import actor_role_label, record_audit
from app.services.identity import (
    apply_consents,
    commit_or_conflict,
    consent_status,
    has_active_consent,
    latest_consents,
    profile_is_complete,
    replace_equipment,
    replace_injuries,
    request_account_deletion,
    upsert_profile,
)

router = APIRouter()

_AUTH_RESPONSES: Dict[int | str, Dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Token tidak valid atau tidak dikirim"},
    403: {"model": ErrorResponse, "description": "Akses ditolak"},
    503: {"model": ErrorResponse, "description": "Auth/database belum dikonfigurasi"},
}


def _me_user(user: User, roles: List[str]) -> MeUser:
    return MeUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        roles=sorted(roles),
        created_at=user.created_at,
    )


def _profile_out(profile: Optional[Profile]) -> Optional[ProfileOut]:
    if profile is None:
        return None
    return ProfileOut.model_validate(profile)


def _injury_out(injuries: List[UserInjury]) -> List[InjuryOut]:
    return [InjuryOut.model_validate(item) for item in injuries]


def _equipment(session: Session, user_id) -> List[str]:
    return list(
        session.scalars(
            select(UserEquipment.equipment)
            .where(UserEquipment.user_id == user_id)
            .order_by(UserEquipment.created_at, UserEquipment.equipment)
        ).all()
    )


def _injuries(session: Session, user_id) -> List[UserInjury]:
    return list(
        session.scalars(
            select(UserInjury)
            .where(UserInjury.user_id == user_id)
            .order_by(UserInjury.created_at, UserInjury.term)
        ).all()
    )


def _profile_response(session: Session, user_id) -> ProfileResponse:
    return ProfileResponse(
        profile=_profile_out(session.get(Profile, user_id)),
        equipment=_equipment(session, user_id),
        injuries=_injury_out(_injuries(session, user_id)),
    )


def _consent_state(
    session: Session,
    user_id,
    policy_version: str,
) -> ConsentStateResponse:
    records = [ConsentRecordOut.model_validate(row) for row in latest_consents(session, user_id)]
    return ConsentStateResponse(
        policy_version=policy_version,
        active=consent_status(session, user_id),
        records=records,
    )


def _iso_utc(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _me_response(session: Session, principal: Principal) -> MeResponse:
    profile = session.get(Profile, principal.user.id)
    return MeResponse(
        user=_me_user(principal.user, principal.roles),
        profile_complete=profile_is_complete(profile),
        consents=consent_status(session, principal.user.id),
    )


@router.get(
    "",
    response_model=MeResponse,
    summary="Ambil user, status profil, dan consent aktif",
    responses=_AUTH_RESPONSES,
)
def get_me(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> MeResponse:
    return _me_response(session, principal)


@router.post(
    "/onboarding",
    response_model=MeResponse,
    summary="Simpan profil, equipment, cedera, dan consent (idempotent)",
    responses={
        **_AUTH_RESPONSES,
        409: {"model": ErrorResponse, "description": "Consent atau versi tidak sesuai"},
        422: {"model": ErrorResponse, "description": "Data profil tidak valid"},
    },
)
def complete_onboarding(
    payload: OnboardingRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> MeResponse:
    user = principal.user
    requested_health = payload.consents.get(ConsentKind.HEALTH_DATA_PROCESSING)
    will_have_health_consent = (
        requested_health
        if requested_health is not None
        else has_active_consent(session, user.id, ConsentKind.HEALTH_DATA_PROCESSING)
    )

    if payload.injuries and not will_have_health_consent:
        raise ConsentRequiredError(
            "Persetujuan pemrosesan data kesehatan diperlukan sebelum menyimpan cedera."
        )

    profile_data = payload.profile.model_dump(mode="json")
    profile = upsert_profile(session, user.id, profile_data, partial=False)

    apply_consents(
        session,
        user_id=user.id,
        actor_role=actor_role_label(principal.roles),
        updates=payload.consents,
        policy_version=settings.consent_policy_version,
    )

    equipment_count: Optional[int] = None
    if payload.equipment is not None:
        equipment = replace_equipment(session, user.id, payload.equipment)
        equipment_count = len(equipment)

    injury_count: Optional[int] = None
    if payload.injuries is not None:
        injuries = replace_injuries(session, user.id, payload.injuries)
        injury_count = len(injuries)

    display_name_changed = False
    if payload.display_name is not None and user.display_name != payload.display_name:
        user.display_name = payload.display_name
        display_name_changed = True

    record_audit(
        session,
        actor_user_id=user.id,
        actor_role=actor_role_label(principal.roles),
        action="profile.onboarding_completed",
        resource_type="user",
        resource_id=str(user.id),
        metadata={
            "profile_fields": sorted(profile_data),
            "profile_complete": profile_is_complete(profile),
            "equipment_count": equipment_count,
            "injury_count": injury_count,
            "consent_kinds": sorted(kind.value for kind in payload.consents),
            "display_name_changed": display_name_changed,
        },
    )
    commit_or_conflict(session)
    return _me_response(session, principal)


@router.get(
    "/profile",
    response_model=ProfileResponse,
    summary="Ambil profil, equipment, dan cedera",
    responses=_AUTH_RESPONSES,
)
def get_profile(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> ProfileResponse:
    return _profile_response(session, principal.user.id)


@router.patch(
    "/profile",
    response_model=ProfileResponse,
    summary="Perbarui sebagian profil",
    responses={
        **_AUTH_RESPONSES,
        422: {"model": ErrorResponse, "description": "Data profil tidak valid"},
    },
)
def patch_profile(
    payload: ProfilePatch,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> ProfileResponse:
    data = payload.model_dump(exclude_none=True, mode="json")
    upsert_profile(session, principal.user.id, data, partial=True)
    record_audit(
        session,
        actor_user_id=principal.user.id,
        actor_role=actor_role_label(principal.roles),
        action="profile.updated",
        resource_type="user",
        resource_id=str(principal.user.id),
        metadata={"fields": sorted(data)},
    )
    commit_or_conflict(session)
    return _profile_response(session, principal.user.id)


@router.put(
    "/equipment",
    response_model=EquipmentResponse,
    summary="Ganti seluruh daftar equipment",
    responses={
        **_AUTH_RESPONSES,
        422: {"model": ErrorResponse, "description": "Equipment tidak valid"},
    },
)
def put_equipment(
    payload: EquipmentUpdate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> EquipmentResponse:
    equipment = replace_equipment(session, principal.user.id, payload.equipment)
    record_audit(
        session,
        actor_user_id=principal.user.id,
        actor_role=actor_role_label(principal.roles),
        action="profile.equipment_replaced",
        resource_type="user",
        resource_id=str(principal.user.id),
        metadata={"count": len(equipment)},
    )
    commit_or_conflict(session)
    return EquipmentResponse(equipment=equipment)


@router.put(
    "/injuries",
    response_model=InjuryResponse,
    summary="Ganti seluruh daftar cedera",
    responses={
        **_AUTH_RESPONSES,
        409: {"model": ErrorResponse, "description": "Consent kesehatan diperlukan"},
        422: {"model": ErrorResponse, "description": "Cedera tidak valid"},
    },
)
def put_injuries(
    payload: InjuryUpdate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> InjuryResponse:
    injuries = replace_injuries(session, principal.user.id, payload.injuries)
    record_audit(
        session,
        actor_user_id=principal.user.id,
        actor_role=actor_role_label(principal.roles),
        action="profile.injuries_replaced",
        resource_type="user",
        resource_id=str(principal.user.id),
        metadata={"count": len(injuries)},
    )
    commit_or_conflict(session)
    return InjuryResponse(injuries=_injury_out(injuries))


@router.get(
    "/consents",
    response_model=ConsentStateResponse,
    summary="Ambil status dan riwayat consent",
    responses=_AUTH_RESPONSES,
)
def get_consents(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ConsentStateResponse:
    return _consent_state(session, principal.user.id, settings.consent_policy_version)


@router.post(
    "/consents",
    response_model=ConsentStateResponse,
    summary="Beri atau cabut consent",
    responses={
        **_AUTH_RESPONSES,
        409: {"model": ErrorResponse, "description": "Versi consent tidak sesuai"},
    },
)
def update_consent(
    payload: ConsentUpdate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ConsentStateResponse:
    if payload.version and payload.version != settings.consent_policy_version:
        raise ConflictError(
            "Versi consent tidak sesuai dengan kebijakan aktif.",
            details={
                "expected": settings.consent_policy_version,
                "received": payload.version,
            },
        )

    apply_consents(
        session,
        user_id=principal.user.id,
        actor_role=actor_role_label(principal.roles),
        updates={payload.kind: payload.granted},
        policy_version=settings.consent_policy_version,
    )
    commit_or_conflict(session)
    return _consent_state(session, principal.user.id, settings.consent_policy_version)


@router.get(
    "/export",
    response_model=ExportResponse,
    summary="Ekspor seluruh data akun sebagai JSON",
    responses=_AUTH_RESPONSES,
)
def export_me(
    response: Response,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> ExportResponse:
    user = principal.user
    profile = session.get(Profile, user.id)
    records = [ConsentRecordOut.model_validate(row) for row in latest_consents(session, user.id)]

    payload = ExportResponse(
        exported_at=datetime.now(UTC),
        user=_me_user(user, principal.roles),
        profile=_profile_out(profile),
        equipment=_equipment(session, user.id),
        injuries=_injury_out(_injuries(session, user.id)),
        consents=records,
        roles=sorted(principal.roles),
        account={
            "created_at": _iso_utc(user.created_at),
            "updated_at": _iso_utc(user.updated_at),
            "deletion_requested_at": _iso_utc(user.deletion_requested_at),
            "deletion_scheduled_for": _iso_utc(user.deletion_scheduled_for),
        },
    )

    record_audit(
        session,
        actor_user_id=user.id,
        actor_role=actor_role_label(principal.roles),
        action="account.exported",
        resource_type="user",
        resource_id=str(user.id),
        metadata={"format": "json", "schema_version": payload.schema_version},
    )
    commit_or_conflict(session)

    response.headers["Content-Disposition"] = 'attachment; filename="jymz-account-export.json"'
    return payload


@router.delete(
    "",
    response_model=DeletionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ajukan penghapusan akun",
    responses=_AUTH_RESPONSES,
)
def delete_me(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> DeletionResponse:
    requested_at, scheduled_for, request_id = request_account_deletion(
        session,
        user=principal.user,
        actor_role=actor_role_label(principal.roles),
        grace_days=settings.account_deletion_grace_days,
    )
    commit_or_conflict(session)
    return DeletionResponse(
        request_id=request_id,
        requested_at=requested_at,
        scheduled_for=scheduled_for,
    )
