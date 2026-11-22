"""P1.3 notification, device, calendar, and integration endpoints."""

from __future__ import annotations

import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_settings
from app.auth.dependencies import Principal, get_current_principal, get_db_session
from app.core.config import Settings
from app.core.errors import NotificationValidationError
from app.schemas.notifications import (
    CalendarTokenResponse,
    DeviceCreate,
    DeviceListResponse,
    DeviceOut,
    IntegrationAuthorizeResponse,
    IntegrationCallbackRequest,
    IntegrationListResponse,
    IntegrationOut,
    NotificationPreferencesOut,
    NotificationPreferencesUpdate,
    OutboxOut,
    TestNotificationRequest,
    UnsubscribeTokenResponse,
)
from app.schemas.recommendation import ErrorResponse
from app.services.audit import actor_role_label
from app.services.integrations import (
    authorize_url,
    disconnect_integration,
    handle_callback,
    list_integrations,
    state_user_id,
)
from app.services.notifications import (
    build_calendar,
    create_calendar_token,
    delete_device,
    device_out,
    enqueue_test_notification,
    get_preferences,
    list_devices,
    outbox_out,
    preferences_out,
    register_device,
    resolve_calendar_token,
    unsubscribe_by_token,
    unsubscribe_token,
    update_preferences,
)

router = APIRouter()
public_router = APIRouter()

_RESPONSES: Dict[int | str, Dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Token tidak valid atau tidak dikirim"},
    403: {"model": ErrorResponse, "description": "Akses ditolak"},
    404: {"model": ErrorResponse, "description": "Device/calendar tidak ditemukan"},
    422: {"model": ErrorResponse, "description": "Data notifikasi tidak valid"},
    503: {"model": ErrorResponse, "description": "Layanan/integrasi belum dikonfigurasi"},
}


@router.get(
    "/notifications",
    response_model=NotificationPreferencesOut,
    summary="Preferensi notifikasi",
    responses=_RESPONSES,
)
def get_notification_preferences(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> NotificationPreferencesOut:
    return preferences_out(get_preferences(session, principal.user.id))


@router.patch(
    "/notifications",
    response_model=NotificationPreferencesOut,
    summary="Perbarui preferensi notifikasi",
    responses=_RESPONSES,
)
def update_notification_preferences(
    payload: NotificationPreferencesUpdate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> NotificationPreferencesOut:
    prefs = update_preferences(
        session,
        user_id=principal.user.id,
        payload=payload,
        actor_role=actor_role_label(principal.roles),
    )
    return preferences_out(prefs)


@router.post(
    "/notifications/test",
    response_model=OutboxOut,
    status_code=status.HTTP_201_CREATED,
    summary="Antrekan notifikasi test",
    responses=_RESPONSES,
)
def test_notification(
    payload: TestNotificationRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> OutboxOut:
    item = enqueue_test_notification(
        session,
        user_id=principal.user.id,
        channel=payload.channel,
        template=payload.template,
        actor_role=actor_role_label(principal.roles),
    )
    return outbox_out(item)


@router.get(
    "/notifications/unsubscribe-token",
    response_model=UnsubscribeTokenResponse,
    summary="Token unsubscribe email",
    responses=_RESPONSES,
)
def get_unsubscribe_token(
    request: Request,
    principal: Principal = Depends(get_current_principal),
    settings: Settings = Depends(get_settings),
) -> UnsubscribeTokenResponse:
    secret = settings.integration_state_secret or settings.token_encryption_key
    if not secret:
        raise NotificationValidationError(
            "Unsubscribe belum dikonfigurasi pada server."
        )
    token = unsubscribe_token(principal.user.id, secret)
    return UnsubscribeTokenResponse(
        token=token,
        unsubscribe_url=str(request.url_for("unsubscribe_email", token=token)),
    )


@router.get(
    "/devices",
    response_model=DeviceListResponse,
    summary="Daftar device push",
    responses=_RESPONSES,
)
def list_devices_endpoint(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> DeviceListResponse:
    return DeviceListResponse(
        items=[device_out(device) for device in list_devices(session, principal.user.id)]
    )


@router.post(
    "/devices",
    response_model=DeviceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Daftarkan device push",
    responses=_RESPONSES,
)
def register_device_endpoint(
    payload: DeviceCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> DeviceOut:
    device = register_device(
        session,
        user_id=principal.user.id,
        payload=payload,
        encryption_key=settings.token_encryption_key,
        actor_role=actor_role_label(principal.roles),
    )
    return device_out(device)


@router.delete(
    "/devices/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hapus device",
    responses=_RESPONSES,
)
def delete_device_endpoint(
    device_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> Response:
    delete_device(
        session,
        user_id=principal.user.id,
        device_id=device_id,
        actor_role=actor_role_label(principal.roles),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/calendar.ics",
    response_class=Response,
    summary="Kalender latihan (authenticated)",
    responses=_RESPONSES,
)
def calendar_ics(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> Response:
    content = build_calendar(session, principal.user.id)
    return Response(
        content=content,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="jymz-calendar.ics"'},
    )


@router.post(
    "/calendar/token",
    response_model=CalendarTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Buat token kalender publik",
    responses=_RESPONSES,
)
def create_calendar_token_endpoint(
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> CalendarTokenResponse:
    token, _ = create_calendar_token(
        session,
        user_id=principal.user.id,
        actor_role=actor_role_label(principal.roles),
    )
    return CalendarTokenResponse(
        token=token,
        calendar_url=str(request.url_for("public_calendar", token=token)),
    )


@router.get(
    "/integrations",
    response_model=IntegrationListResponse,
    summary="Daftar integrasi aktif",
    responses=_RESPONSES,
)
def list_integrations_endpoint(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> IntegrationListResponse:
    return IntegrationListResponse(
        items=list_integrations(session, user_id=principal.user.id)
    )


@router.delete(
    "/integrations/{provider}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Putuskan integrasi",
    responses=_RESPONSES,
)
def disconnect_integration_endpoint(
    provider: str,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> Response:
    disconnect_integration(
        session,
        user_id=principal.user.id,
        provider=provider,
        actor_role=actor_role_label(principal.roles),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/integrations/{provider}/authorize",
    response_model=IntegrationAuthorizeResponse,
    summary="Mulai OAuth integrasi",
    responses=_RESPONSES,
)
def integration_authorize_endpoint(
    provider: str,
    principal: Principal = Depends(get_current_principal),
    settings: Settings = Depends(get_settings),
) -> IntegrationAuthorizeResponse:
    return authorize_url(
        user_id=principal.user.id,
        provider=provider,
        settings=settings,
    )


@public_router.get(
    "/calendar/{token}.ics",
    response_class=Response,
    name="public_calendar",
    summary="Kalender publik read-only",
)
def public_calendar(token: str, session: Session = Depends(get_db_session)) -> Response:
    content = resolve_calendar_token(session, token)
    return Response(
        content=content,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="jymz-calendar.ics"'},
    )


@public_router.get(
    "/notifications/unsubscribe/{token}",
    name="unsubscribe_email",
    summary="Unsubscribe email",
)
def unsubscribe_email(
    token: str,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    secret = settings.integration_state_secret or settings.token_encryption_key
    if not secret:
        raise NotificationValidationError(
            "Unsubscribe belum dikonfigurasi pada server."
        )
    unsubscribe_by_token(session, token, secret)
    return {"status": "unsubscribed", "channel": "email"}


@public_router.post(
    "/integrations/{provider}/callback",
    response_model=IntegrationOut,
    summary="Callback OAuth integrasi",
)
def integration_callback(
    provider: str,
    payload: IntegrationCallbackRequest,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> IntegrationOut:
    user_id = state_user_id(payload.state, provider, settings)
    return handle_callback(
        session,
        user_id=user_id,
        provider=provider,
        code=payload.code,
        state=payload.state,
        settings=settings,
        actor_role="user",
    )
