"""Integration tests for P2.3 operational status."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import NotificationOutbox, User, UserRole
from app.main import create_app

SECRET = "test-secret-" + ("x" * 40)
ISSUER = "https://issuer.test"
AUDIENCE = "fitness-api-test"


@pytest.fixture()
def ops_settings(dataset_path: Path, tmp_path: Path) -> Settings:
    database_path = (tmp_path / "ops.db").as_posix()
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
        notifications_enabled=True,
        ops_enabled=True,
        auth_dev_mode=True,
        auth_dev_secret=SECRET,
        auth_issuer=ISSUER,
        auth_audience=AUDIENCE,
    )


@pytest.fixture()
def ops_app(ops_settings: Settings):
    return create_app(ops_settings)


@pytest.fixture()
def ops_client(ops_app):
    with TestClient(ops_app) as client:
        yield client


@pytest.fixture()
def db_session(ops_client, ops_app) -> Session:
    session = ops_app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def token_factory():
    def make_token(sub: str) -> str:
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


def make_admin(client, db_session: Session, token_factory) -> dict:
    headers = {"Authorization": f"Bearer {token_factory('ops-admin')}"}
    assert client.get("/api/v1/me", headers=headers).status_code == 200
    user = db_session.scalar(select(User).where(User.auth_subject == "ops-admin"))
    assert user is not None
    db_session.add(UserRole(user_id=user.id, role="platform_admin"))
    db_session.commit()
    return headers


@pytest.mark.integration
def test_ops_is_feature_flagged(client):
    assert client.get("/api/v1/admin/ops/status").status_code == 404


@pytest.mark.integration
def test_ops_requires_platform_admin(ops_client, token_factory):
    headers = {"Authorization": f"Bearer {token_factory('regular-user')}"}
    assert ops_client.get("/api/v1/me", headers=headers).status_code == 200
    response = ops_client.get("/api/v1/admin/ops/status", headers=headers)
    assert response.status_code == 403


@pytest.mark.integration
def test_ops_status_includes_outbox_and_infra(
    ops_client, db_session, token_factory
):
    admin_headers = make_admin(ops_client, db_session, token_factory)
    user = db_session.scalar(select(User).where(User.auth_subject == "ops-admin"))
    assert user is not None
    now = datetime.now(UTC)
    db_session.add_all(
        [
            NotificationOutbox(
                owner_user_id=user.id,
                channel="email",
                template="test",
                payload={},
                status="pending",
                attempts=0,
                max_attempts=3,
                idempotency_key=f"ops-pending-{uuid.uuid4()}",
                scheduled_at=now - timedelta(minutes=5),
            ),
            NotificationOutbox(
                owner_user_id=user.id,
                channel="email",
                template="test",
                payload={},
                status="failed",
                attempts=1,
                max_attempts=3,
                idempotency_key=f"ops-failed-{uuid.uuid4()}",
                scheduled_at=now - timedelta(minutes=10),
            ),
            NotificationOutbox(
                owner_user_id=user.id,
                channel="email",
                template="test",
                payload={},
                status="sent",
                attempts=1,
                max_attempts=3,
                idempotency_key=f"ops-sent-{uuid.uuid4()}",
                scheduled_at=now - timedelta(hours=1),
                sent_at=now - timedelta(minutes=30),
            ),
        ]
    )
    db_session.commit()

    response = ops_client.get("/api/v1/admin/ops/status", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["migration_head"] is None  # db_auto_create, no Alembic run
    assert body["redis"] == "not_configured"
    assert body["rate_limit"] == "memory"
    assert body["dataset_size"] == 222
    assert body["outbox"]["pending"] == 1
    assert body["outbox"]["failed"] == 1
    assert body["outbox"]["sent"] == 1
    assert body["outbox"]["due_pending"] == 2
    assert body["outbox"]["oldest_due_at"] is not None
    assert body["outbox"]["last_sent_at"] is not None


@pytest.mark.integration
def test_ready_reports_redis_state(ops_client):
    response = ops_client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["database"] == "ok"
    assert body["redis"] == "not_configured"
    assert body["rate_limit"] == "memory"
    assert body["degraded"] is False


@pytest.mark.integration
def test_ops_reports_degraded_when_redis_unavailable(
    ops_client, ops_app, db_session, token_factory
):
    admin_headers = make_admin(ops_client, db_session, token_factory)
    settings = ops_app.state.settings
    original_uri = settings.rate_limit_storage_uri
    original_enabled = settings.rate_limit_enabled
    settings.rate_limit_storage_uri = "redis://127.0.0.1:6399/0"
    settings.rate_limit_enabled = True
    try:
        response = ops_client.get("/api/v1/admin/ops/status", headers=admin_headers)
    finally:
        settings.rate_limit_storage_uri = original_uri
        settings.rate_limit_enabled = original_enabled
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["redis"] == "unavailable"
    assert body["rate_limit"] == "redis"


@pytest.mark.integration
def test_ops_openapi(ops_client):
    paths = ops_client.get("/openapi.json").json()["paths"]
    assert "/api/v1/admin/ops/status" in paths
