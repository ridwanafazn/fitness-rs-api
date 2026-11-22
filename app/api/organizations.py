"""P2.1 free organizations, memberships, and invitations (no billing)."""

from __future__ import annotations

import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, get_current_principal, get_db_session
from app.schemas.organizations import (
    OrganizationCreate,
    OrganizationInvitationCreate,
    OrganizationInvitationCreated,
    OrganizationInvitationListResponse,
    OrganizationListResponse,
    OrganizationMemberListResponse,
    OrganizationMemberUpdate,
    OrganizationOut,
    OrganizationSummary,
    OrganizationUpdate,
)
from app.schemas.recommendation import ErrorResponse
from app.services.audit import actor_role_label
from app.services.organizations import (
    accept_invitation,
    create_invitation,
    create_organization,
    decline_invitation,
    get_organization,
    leave_organization,
    list_invitations,
    list_members,
    list_organizations,
    organization_out,
    organization_summary,
    remove_member,
    update_member_role,
    update_organization,
)

router = APIRouter()
me_router = APIRouter()
invitation_router = APIRouter()

_RESPONSES: Dict[int | str, Dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Token tidak valid atau tidak dikirim"},
    403: {"model": ErrorResponse, "description": "Akses organisasi ditolak"},
    404: {"model": ErrorResponse, "description": "Organisasi/member/undangan tidak ditemukan"},
    409: {"model": ErrorResponse, "description": "Konflik membership atau undangan"},
    422: {"model": ErrorResponse, "description": "Data organisasi tidak valid"},
    503: {"model": ErrorResponse, "description": "Auth/database belum dikonfigurasi"},
}


@router.post(
    "",
    response_model=OrganizationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Buat organisasi",
    responses=_RESPONSES,
)
def create_organization_endpoint(
    payload: OrganizationCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> OrganizationOut:
    org = create_organization(
        session,
        user_id=principal.user.id,
        payload=payload,
        actor_role=actor_role_label(principal.roles),
    )
    return organization_out(org, "owner")


@me_router.get(
    "/orgs",
    response_model=OrganizationListResponse,
    summary="Daftar organisasi saya",
    responses=_RESPONSES,
)
def list_my_organizations(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> OrganizationListResponse:
    return OrganizationListResponse(
        items=list_organizations(session, user_id=principal.user.id)
    )


@router.get(
    "/{org_id}",
    response_model=OrganizationOut,
    summary="Detail organisasi",
    responses=_RESPONSES,
)
def get_organization_endpoint(
    org_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> OrganizationOut:
    org, membership = get_organization(
        session,
        org_id=org_id,
        user_id=principal.user.id,
    )
    return organization_out(org, membership.role)


@router.patch(
    "/{org_id}",
    response_model=OrganizationOut,
    summary="Perbarui organisasi",
    responses=_RESPONSES,
)
def update_organization_endpoint(
    org_id: uuid.UUID,
    payload: OrganizationUpdate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> OrganizationOut:
    org = update_organization(
        session,
        org_id=org_id,
        user_id=principal.user.id,
        payload=payload,
        actor_role=actor_role_label(principal.roles),
    )
    _, membership = get_organization(
        session,
        org_id=org_id,
        user_id=principal.user.id,
    )
    return organization_out(org, membership.role)


@router.get(
    "/{org_id}/members",
    response_model=OrganizationMemberListResponse,
    summary="Daftar member organisasi",
    responses=_RESPONSES,
)
def list_organization_members(
    org_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> OrganizationMemberListResponse:
    return OrganizationMemberListResponse(
        items=list_members(session, org_id=org_id, user_id=principal.user.id)
    )


@router.patch(
    "/{org_id}/members/{user_id}",
    response_model=OrganizationMemberListResponse,
    summary="Ubah role member",
    responses=_RESPONSES,
)
def update_organization_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: OrganizationMemberUpdate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> OrganizationMemberListResponse:
    update_member_role(
        session,
        org_id=org_id,
        actor_user_id=principal.user.id,
        target_user_id=user_id,
        new_role=payload.role,
        actor_role=actor_role_label(principal.roles),
    )
    return OrganizationMemberListResponse(
        items=list_members(session, org_id=org_id, user_id=principal.user.id)
    )


@router.delete(
    "/{org_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Keluarkan member",
    responses=_RESPONSES,
)
def remove_organization_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> Response:
    remove_member(
        session,
        org_id=org_id,
        actor_user_id=principal.user.id,
        target_user_id=user_id,
        actor_role=actor_role_label(principal.roles),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{org_id}/leave",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Keluar dari organisasi",
    responses=_RESPONSES,
)
def leave_organization_endpoint(
    org_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> Response:
    leave_organization(
        session,
        org_id=org_id,
        user_id=principal.user.id,
        actor_role=actor_role_label(principal.roles),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{org_id}/summary",
    response_model=OrganizationSummary,
    summary="Ringkasan agregat organisasi",
    responses=_RESPONSES,
)
def organization_summary_endpoint(
    org_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> OrganizationSummary:
    return organization_summary(
        session,
        org_id=org_id,
        user_id=principal.user.id,
    )


@router.get(
    "/{org_id}/invitations",
    response_model=OrganizationInvitationListResponse,
    summary="Daftar undangan organisasi",
    responses=_RESPONSES,
)
def list_organization_invitations(
    org_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> OrganizationInvitationListResponse:
    return OrganizationInvitationListResponse(
        items=list_invitations(session, org_id=org_id, user_id=principal.user.id)
    )


@router.post(
    "/{org_id}/invitations",
    response_model=OrganizationInvitationCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Undang member organisasi",
    responses=_RESPONSES,
)
def create_organization_invitation(
    org_id: uuid.UUID,
    payload: OrganizationInvitationCreate,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> OrganizationInvitationCreated:
    invitation, token = create_invitation(
        session,
        org_id=org_id,
        user_id=principal.user.id,
        payload=payload,
        actor_role=actor_role_label(principal.roles),
    )
    invite_url = str(
        request.url_for("accept_organization_invitation", token=token)
    )
    return OrganizationInvitationCreated(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        expires_at=invitation.expires_at,
        token=token,
        invite_url=invite_url,
    )


@invitation_router.post(
    "/{token}/accept",
    response_model=OrganizationOut,
    name="accept_organization_invitation",
    summary="Terima undangan organisasi",
    responses=_RESPONSES,
)
def accept_organization_invitation(
    token: str,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> OrganizationOut:
    membership = accept_invitation(
        session,
        user=principal.user,
        token=token,
        actor_role=actor_role_label(principal.roles),
    )
    org, _ = get_organization(
        session,
        org_id=membership.organization_id,
        user_id=principal.user.id,
    )
    return organization_out(org, membership.role)


@invitation_router.post(
    "/{token}/decline",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Tolak undangan organisasi",
    responses=_RESPONSES,
)
def decline_organization_invitation(
    token: str,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> Response:
    decline_invitation(
        session,
        user=principal.user,
        token=token,
        actor_role=actor_role_label(principal.roles),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
