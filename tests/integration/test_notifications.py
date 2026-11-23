"""Integration tests for P1.3 notifications, calendar, devices, and integrations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import jwt
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    Device,
    IntegrationToken,
    NotificationOutbox,
    NotificationPreference,
)
from app.main import create_app
from app.services import integrations as integration_service
from app.services import notifications as notification_service

SECRET = "test-secret-" + ("x" * 40)
ISSUER = "https://issuer.test"
AUDIENCE = "fitness-api-test"


@pytest.fixture()
def notification_settings(dataset_path: Path, tmp_path: Path) -> Settings:
    database_path = (tmp_path / "notifications.db").as_posix()
    return Settings(
        environment="test",
        dataset_path=dataset_path,
        rate_limit_enabled=False,
        metrics_enabled=False,
        docs_enabled=True,
        ga_num_generations=8,
        ga_sol_per_pop=10,
        ga_num_parents_mating=4,
        ga_keep_parents=2,
        request_timeout_seconds=30.0,
        database_url=f"sqlite+pysqlite:///{database_path}",
        db_auto_create=True,
        auth_enabled=True,
        auth_profiles_enabled=True,
        plans_enabled=True,
        workouts_enabled=True,
        feedback_enabled=True,
        progress_enabled=True,
        trainer_enabled=True,
        notifications_enabled=True,
        notification_delivery_mode="log",
        token_encryption_key=Fernet.generate_key().decode(),
        integration_state_secret="integration-state-secret-" + ("z" * 20),
        strava_client_id="12345",
        strava_client_secret="strava-secret",
        strava_redirect_uri="https://example.com/api/v1/integrations/strava/callback",
        auth_dev_mode=True,
        auth_dev_secret=SECRET,
        auth_issuer=ISSUER,
        auth_audience=AUDIENCE,
    )


@pytest.fixture()
def notification_app(notification_settings: Settings):
    return create_app(notification_settings)


@pytest.fixture()
def notification_client(notification_app):
    with TestClient(notification_app) as client:
        yield client


@pytest.fixture()
def db_session(notification_client, notification_app) -> Session:
    session = notification_app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def token_factory():
    def make_token(sub: str = "user-1") -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": sub,
                "iss": ISSUER,
                "aud": AUDIENCE,
                "iat": now,
                "exp": now + timedelta(minutes=10),
                "email": f"{sub}@example.com",
                "emailVerified": True,
                "name": sub,
            },
            SECRET,
            algorithm="HS256",
        )

    return make_token


@pytest.fixture()
def auth_headers(token_factory) -> dict:
    return {"Authorization": f"Bearer {token_factory()}"}


def create_plan(client, headers):
    return client.post(
        "/api/v1/plans",
        json={
            "recommendation": {
                "gender": "male",
                "height_cm": 175,
                "weight_kg": 72,
                "injuries": [],
                "available_days": 2,
                "preferred_body_part": [],
                "preferred_equipment": [],
                "seed": 42,
            },
            "title": "Calendar Plan",
        },
        headers={**headers, "Idempotency-Key": "notif-plan-1"},
    )


def count(session: Session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


@pytest.mark.integration
def test_notifications_are_feature_flagged(client):
    assert client.get("/api/v1/me/notifications").status_code == 404
    assert client.get("/api/v1/me/devices").status_code == 404


@pytest.mark.integration
def test_notification_preferences(notification_client, auth_headers):
    initial = notification_client.get("/api/v1/me/notifications", headers=auth_headers)
    assert initial.status_code == 200
    assert initial.json()["email_enabled"] is False
    assert initial.json()["reminder_enabled"] is False

    updated = notification_client.patch(
        "/api/v1/me/notifications",
        json={
            "email_enabled": True,
            "push_enabled": True,
            "reminder_enabled": True,
            "reminder_time": "18:30",
            "timezone": "Asia/Jakarta",
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "07:00",
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["email_enabled"] is True
    assert body["reminder_time"] == "18:30"
    assert body["timezone"] == "Asia/Jakarta"
    assert body["quiet_hours_start"] == "22:00"

    invalid_time = notification_client.patch(
        "/api/v1/me/notifications",
        json={"reminder_time": "25:00"},
        headers=auth_headers,
    )
    assert invalid_time.status_code == 422

    invalid_timezone = notification_client.patch(
        "/api/v1/me/notifications",
        json={"timezone": "Mars/Olympus"},
        headers=auth_headers,
    )
    assert invalid_timezone.status_code == 422


@pytest.mark.integration
def test_reminder_requires_channel(notification_client, token_factory):
    headers = {"Authorization": f"Bearer {token_factory('no-channel')}"}
    response = notification_client.patch(
        "/api/v1/me/notifications",
        json={"reminder_enabled": True},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "notification_invalid"


@pytest.mark.integration
def test_device_registration_and_deletion(
    notification_client,
    auth_headers,
    db_session,
):
    token = "push-token-" + uuid.uuid4().hex
    created = notification_client.post(
        "/api/v1/me/devices",
        json={"token": token, "platform": "android", "device_name": "Pixel"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    device_id = created.json()["id"]
    assert created.json()["has_token"] is True

    duplicate = notification_client.post(
        "/api/v1/me/devices",
        json={"token": token, "platform": "android", "device_name": "Pixel 2"},
        headers=auth_headers,
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == device_id
    assert count(db_session, Device) == 1
    stored = db_session.scalar(select(Device))
    assert stored is not None
    assert stored.token_hash != token
    assert stored.token_ciphertext != token

    listed = notification_client.get("/api/v1/me/devices", headers=auth_headers)
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1

    deleted = notification_client.delete(
        f"/api/v1/me/devices/{device_id}", headers=auth_headers
    )
    assert deleted.status_code == 204
    assert notification_client.get(
        "/api/v1/me/devices", headers=auth_headers
    ).json()["items"] == []


@pytest.mark.integration
def test_test_notification_and_outbox_processing(
    notification_client,
    auth_headers,
    notification_app,
    db_session,
):
    disabled = notification_client.post(
        "/api/v1/me/notifications/test",
        json={"channel": "email"},
        headers=auth_headers,
    )
    assert disabled.status_code == 422

    notification_client.patch(
        "/api/v1/me/notifications",
        json={"email_enabled": True},
        headers=auth_headers,
    )
    response = notification_client.post(
        "/api/v1/me/notifications/test",
        json={"channel": "email"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    item_id = response.json()["id"]
    assert count(db_session, NotificationOutbox) == 1

    session = notification_app.state.session_factory()
    try:
        result = notification_service.process_outbox(
            session,
            mode="log",
            webhook_url=None,
        )
    finally:
        session.close()
    assert result["sent"] == 1
    stored = db_session.get(NotificationOutbox, uuid.UUID(item_id))
    assert stored is not None
    assert stored.status == "sent"


@pytest.mark.integration
def test_outbox_retry_then_success(
    notification_client,
    auth_headers,
    notification_app,
    db_session,
    monkeypatch,
):
    notification_client.patch(
        "/api/v1/me/notifications",
        json={"email_enabled": True},
        headers=auth_headers,
    )
    created = notification_client.post(
        "/api/v1/me/notifications/test",
        json={"channel": "email"},
        headers=auth_headers,
    ).json()

    calls = {"count": 0}

    def flaky_deliver(item, *, mode, webhook_url):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary failure")

    monkeypatch.setattr(notification_service, "_deliver", flaky_deliver)
    session = notification_app.state.session_factory()
    try:
        first = notification_service.process_outbox(
            session,
            mode="log",
            webhook_url=None,
        )
    finally:
        session.close()
    assert first["retry"] == 1

    stored = db_session.get(NotificationOutbox, uuid.UUID(created["id"]))
    assert stored is not None
    assert stored.attempts == 1
    stored.scheduled_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    session = notification_app.state.session_factory()
    try:
        second = notification_service.process_outbox(
            session,
            mode="log",
            webhook_url=None,
        )
    finally:
        session.close()
    assert second["sent"] == 1


@pytest.mark.integration
def test_outbox_lease_is_cleared_after_delivery(
    notification_client,
    auth_headers,
    notification_app,
    db_session,
    monkeypatch,
):
    notification_client.patch(
        "/api/v1/me/notifications",
        json={"email_enabled": True},
        headers=auth_headers,
    )
    created = notification_client.post(
        "/api/v1/me/notifications/test",
        json={"channel": "email"},
        headers=auth_headers,
    ).json()
    observed = {}

    def deliver(item, *, mode, webhook_url):
        observed["locked_by"] = item.locked_by
        observed["locked_until"] = item.locked_until

    monkeypatch.setattr(notification_service, "_deliver", deliver)
    session = notification_app.state.session_factory()
    try:
        result = notification_service.process_outbox(
            session,
            mode="log",
            webhook_url=None,
            worker_id="test-worker",
            lease_seconds=60,
        )
    finally:
        session.close()
    assert result["sent"] == 1
    assert observed["locked_by"] == "test-worker"
    assert observed["locked_until"] is not None
    stored = db_session.get(NotificationOutbox, uuid.UUID(created["id"]))
    assert stored is not None
    assert stored.status == "sent"
    assert stored.locked_by is None
    assert stored.locked_until is None


@pytest.mark.integration
def test_outbox_lease_skips_locked_and_expires(
    notification_client,
    auth_headers,
    notification_app,
    db_session,
):
    notification_client.patch(
        "/api/v1/me/notifications",
        json={"email_enabled": True},
        headers=auth_headers,
    )
    created = notification_client.post(
        "/api/v1/me/notifications/test",
        json={"channel": "email"},
        headers=auth_headers,
    ).json()
    stored = db_session.get(NotificationOutbox, uuid.UUID(created["id"]))
    assert stored is not None
    stored.locked_until = datetime.now(UTC) + timedelta(minutes=5)
    stored.locked_by = "other-worker"
    db_session.commit()

    session = notification_app.state.session_factory()
    try:
        skipped = notification_service.process_outbox(
            session,
            mode="log",
            webhook_url=None,
        )
    finally:
        session.close()
    assert skipped["processed"] == 0

    db_session.refresh(stored)
    stored.locked_until = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()
    session = notification_app.state.session_factory()
    try:
        claimed = notification_service.process_outbox(
            session,
            mode="log",
            webhook_url=None,
        )
    finally:
        session.close()
    assert claimed["sent"] == 1


@pytest.mark.integration
def test_due_reminders_are_idempotent(
    notification_client,
    auth_headers,
    notification_app,
    db_session,
):
    create_plan(notification_client, auth_headers)
    notification_client.patch(
        "/api/v1/me/notifications",
        json={
            "email_enabled": True,
            "reminder_enabled": True,
            "reminder_time": "00:00",
            "timezone": "Asia/Jakarta",
        },
        headers=auth_headers,
    )
    session = notification_app.state.session_factory()
    try:
        first = notification_service.enqueue_due_reminders(session)
        second = notification_service.enqueue_due_reminders(session)
    finally:
        session.close()
    assert first >= 1
    assert second >= 1
    assert count(db_session, NotificationOutbox) == 1


@pytest.mark.integration
def test_calendar_authenticated_and_public(
    notification_client,
    auth_headers,
):
    create_plan(notification_client, auth_headers)

    authenticated = notification_client.get(
        "/api/v1/me/calendar.ics", headers=auth_headers
    )
    assert authenticated.status_code == 200
    assert authenticated.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in authenticated.text
    assert "BEGIN:VEVENT" in authenticated.text

    token_response = notification_client.post(
        "/api/v1/me/calendar/token",
        headers=auth_headers,
    )
    assert token_response.status_code == 201
    calendar_url = token_response.json()["calendar_url"]
    path = urlparse(calendar_url).path
    public = notification_client.get(path)
    assert public.status_code == 200
    assert "BEGIN:VEVENT" in public.text

    invalid = notification_client.get("/api/v1/calendar/not-a-token.ics")
    assert invalid.status_code == 404


@pytest.mark.integration
def test_email_unsubscribe(
    notification_client,
    auth_headers,
    db_session,
):
    notification_client.patch(
        "/api/v1/me/notifications",
        json={"email_enabled": True},
        headers=auth_headers,
    )
    token_response = notification_client.get(
        "/api/v1/me/notifications/unsubscribe-token",
        headers=auth_headers,
    )
    assert token_response.status_code == 200
    path = urlparse(token_response.json()["unsubscribe_url"]).path
    response = notification_client.get(path)
    assert response.status_code == 200
    prefs = db_session.scalar(select(NotificationPreference))
    assert prefs is not None
    assert prefs.email_enabled is False


@pytest.mark.integration
def test_strava_authorize_callback_and_disconnect(
    notification_client,
    auth_headers,
    db_session,
    monkeypatch,
):
    authorize = notification_client.post(
        "/api/v1/me/integrations/strava/authorize",
        headers=auth_headers,
    )
    assert authorize.status_code == 200, authorize.text
    body = authorize.json()
    assert body["authorize_url"].startswith("https://www.strava.com/oauth/authorize?")
    assert body["state"]

    bad_state = notification_client.post(
        "/api/v1/integrations/strava/callback",
        json={"code": "code", "state": "bad-state"},
    )
    assert bad_state.status_code == 403

    def fake_exchange(code, settings):
        return {
            "access_token": "strava-access-token",
            "refresh_token": "strava-refresh-token",
            "expires_at": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            "scope": "read,activity:read_all",
            "athlete": {"id": 999},
        }

    monkeypatch.setattr(integration_service, "_exchange_strava_code", fake_exchange)
    callback = notification_client.post(
        "/api/v1/integrations/strava/callback",
        json={"code": "code", "state": body["state"]},
    )
    assert callback.status_code == 200, callback.text
    assert callback.json()["provider"] == "strava"
    assert callback.json()["status"] == "active"

    listed = notification_client.get("/api/v1/me/integrations", headers=auth_headers)
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1
    stored = db_session.scalar(select(IntegrationToken))
    assert stored is not None
    assert stored.access_token_ciphertext != "strava-access-token"
    assert stored.refresh_token_ciphertext != "strava-refresh-token"

    disconnected = notification_client.delete(
        "/api/v1/me/integrations/strava",
        headers=auth_headers,
    )
    assert disconnected.status_code == 204
    assert notification_client.get(
        "/api/v1/me/integrations", headers=auth_headers
    ).json()["items"] == []


@pytest.mark.integration
def test_unsupported_integration_provider(notification_client, auth_headers):
    response = notification_client.post(
        "/api/v1/me/integrations/google_fit/authorize",
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "integration_unsupported"


@pytest.mark.integration
def test_notification_openapi(notification_client):
    document = notification_client.get("/openapi.json").json()
    paths = document["paths"]
    assert "/api/v1/me/notifications" in paths
    assert "/api/v1/me/devices" in paths
    assert "/api/v1/me/calendar.ics" in paths
    assert "/api/v1/me/calendar/token" in paths
    assert "/api/v1/calendar/{token}.ics" in paths
    assert "/api/v1/notifications/unsubscribe/{token}" in paths
    assert "/api/v1/me/integrations" in paths
    assert "/api/v1/me/integrations/{provider}/authorize" in paths
    assert "/api/v1/integrations/{provider}/callback" in paths
