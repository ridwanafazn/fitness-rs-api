"""Integration tests for P0.1 identity, profile, consent, and export."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import AuditLog, Consent, Profile, User, UserEquipment, UserInjury, UserRole
from app.main import create_app

SECRET = "test-secret-" + ("x" * 40)
ISSUER = "https://issuer.test"
AUDIENCE = "fitness-api-test"


@pytest.fixture()
def auth_settings(dataset_path: Path, tmp_path: Path) -> Settings:
    database_path = (tmp_path / "auth.db").as_posix()
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
        auth_dev_mode=True,
        auth_dev_secret=SECRET,
        auth_issuer=ISSUER,
        auth_audience=AUDIENCE,
        consent_policy_version="2026-01",
        account_deletion_grace_days=30,
    )


@pytest.fixture()
def auth_app(auth_settings: Settings):
    return create_app(auth_settings)


@pytest.fixture()
def auth_client(auth_app):
    with TestClient(auth_app) as client:
        yield client


@pytest.fixture()
def db_session(auth_client, auth_app) -> Session:
    session = auth_app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def token_factory():
    def make_token(sub: str = "user-1", **overrides):
        now = datetime.now(UTC)
        payload = {
            "sub": sub,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "email": f"{sub}@example.com",
            "email_verified": True,
            "name": f"User {sub}",
        }
        for key, value in overrides.items():
            if value is None:
                payload.pop(key, None)
            else:
                payload[key] = value
        return jwt.encode(payload, SECRET, algorithm="HS256")

    return make_token


@pytest.fixture()
def auth_headers(token_factory):
    return {"Authorization": f"Bearer {token_factory()}"}


def profile_body(**overrides) -> dict:
    body = {
        "gender": "male",
        "height_cm": 175,
        "weight_kg": 72,
        "goal": "muscle_gain",
        "experience": "beginner",
        "session_minutes": 60,
        "timezone": "Asia/Jakarta",
        "locale": "id-ID",
        "unit_system": "metric",
    }
    body.update(overrides)
    return body


def onboarding_body(**overrides) -> dict:
    body = {
        "display_name": "Ridwan",
        "profile": profile_body(),
        "equipment": ["dumbbell", "bodyweight"],
        "injuries": ["knee pain"],
        "consents": {
            "health_data_processing": True,
            "research_analytics": True,
        },
    }
    body.update(overrides)
    return body


def count(session: Session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


@pytest.mark.integration
def test_profiles_endpoint_is_feature_flagged(client):
    response = client.get("/api/v1/me")
    assert response.status_code == 404


@pytest.mark.integration
def test_missing_token_returns_bearer_challenge(auth_client):
    response = auth_client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert "Bearer" in response.headers["www-authenticate"]


@pytest.mark.integration
@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": datetime.now(UTC) - timedelta(minutes=5)},
        {"iss": "https://wrong-issuer.test"},
        {"aud": "wrong-audience"},
        {"sub": None},
    ],
)
def test_invalid_claims_are_rejected(auth_client, token_factory, overrides):
    token = token_factory(**overrides)
    response = auth_client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.integration
def test_bad_signature_is_rejected(auth_client):
    token = jwt.encode(
        {
            "sub": "user-1",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        "a-different-secret-" + ("y" * 40),
        algorithm="HS256",
    )
    response = auth_client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


@pytest.mark.integration
def test_unsigned_token_is_rejected(auth_client):
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT"}).encode()
    ).rstrip(b"=")
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "sub": "user-1",
                "iss": ISSUER,
                "aud": AUDIENCE,
                "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
            }
        ).encode()
    ).rstrip(b"=")
    token = f"{header.decode()}.{payload.decode()}."

    response = auth_client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


@pytest.mark.integration
def test_first_login_is_idempotent_and_assigns_user_role(
    auth_client, auth_headers, db_session
):
    first = auth_client.get("/api/v1/me", headers=auth_headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["user"]["roles"] == ["user"]
    assert body["profile_complete"] is False
    assert body["consents"] == {
        "health_data_processing": False,
        "research_analytics": False,
        "trainer_sharing": False,
        "marketing": False,
    }

    second = auth_client.get("/api/v1/me", headers=auth_headers)
    assert second.status_code == 200
    assert second.json()["user"]["id"] == body["user"]["id"]

    assert count(db_session, User) == 1
    assert count(db_session, UserRole) == 1
    role = db_session.scalar(select(UserRole.role))
    assert role == "user"

    actions = set(db_session.scalars(select(AuditLog.action)).all())
    assert "auth.first_login" in actions


@pytest.mark.integration
def test_jwt_roles_are_not_trusted(auth_client, token_factory):
    token = token_factory(roles=["platform_admin"])
    response = auth_client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["roles"] == ["user"]


@pytest.mark.integration
def test_unverified_email_is_not_stored(auth_client, token_factory):
    token = token_factory(sub="unverified", email_verified=False)
    response = auth_client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["email"] is None


@pytest.mark.integration
def test_neon_auth_camel_case_email_verified_claim_is_supported(auth_client, token_factory):
    token = token_factory(
        sub="neon-user",
        email_verified=None,
        emailVerified=True,
    )
    response = auth_client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["email"] == "neon-user@example.com"


@pytest.mark.integration
def test_onboarding_roundtrip(auth_client, auth_headers, db_session):
    response = auth_client.post(
        "/api/v1/me/onboarding",
        json=onboarding_body(),
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["profile_complete"] is True
    assert body["user"]["display_name"] == "Ridwan"
    assert body["consents"]["health_data_processing"] is True
    assert body["consents"]["research_analytics"] is True
    assert body["consents"]["trainer_sharing"] is False

    profile_response = auth_client.get("/api/v1/me/profile", headers=auth_headers)
    assert profile_response.status_code == 200
    profile = profile_response.json()
    assert profile["profile"]["goal"] == "muscle_gain"
    assert profile["profile"]["timezone"] == "Asia/Jakarta"
    assert profile["equipment"] == ["dumbbell", "body weight"]
    assert len(profile["injuries"]) == 1
    assert profile["injuries"][0]["term"] == "knee"
    assert "quadriceps" in profile["injuries"][0]["body_parts"]

    consents = auth_client.get("/api/v1/me/consents", headers=auth_headers).json()
    assert consents["active"]["health_data_processing"] is True
    assert len(consents["records"]) == 2

    assert count(db_session, Profile) == 1
    assert count(db_session, UserEquipment) == 2
    assert count(db_session, UserInjury) == 1
    assert count(db_session, Consent) == 2


@pytest.mark.integration
def test_onboarding_is_idempotent(auth_client, auth_headers, db_session):
    for _ in range(2):
        response = auth_client.post(
            "/api/v1/me/onboarding",
            json=onboarding_body(),
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text

    assert count(db_session, User) == 1
    assert count(db_session, Profile) == 1
    assert count(db_session, UserEquipment) == 2
    assert count(db_session, UserInjury) == 1
    assert count(db_session, Consent) == 2


@pytest.mark.integration
def test_injuries_require_health_consent(auth_client, auth_headers, db_session):
    response = auth_client.post(
        "/api/v1/me/onboarding",
        json=onboarding_body(consents={}),
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "consent_required"
    assert count(db_session, Profile) == 0
    assert count(db_session, UserInjury) == 0

    response = auth_client.post(
        "/api/v1/me/onboarding",
        json=onboarding_body(
            consents={"health_data_processing": True},
        ),
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert count(db_session, UserInjury) == 1


@pytest.mark.integration
def test_unknown_injury_and_equipment_are_rejected(
    auth_client, auth_headers, db_session
):
    response = auth_client.post(
        "/api/v1/me/onboarding",
        json=onboarding_body(injuries=["broken soul"]),
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_injury"
    assert count(db_session, UserInjury) == 0

    auth_client.post("/api/v1/me/onboarding", json=onboarding_body(), headers=auth_headers)

    response = auth_client.put(
        "/api/v1/me/equipment",
        json={"equipment": ["space gym"]},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.integration
def test_invalid_profile_values_are_rejected(auth_client, auth_headers):
    response = auth_client.post(
        "/api/v1/me/onboarding",
        json=onboarding_body(profile=profile_body(timezone="Mars/Olympus")),
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

    response = auth_client.post(
        "/api/v1/me/onboarding",
        json=onboarding_body(profile=profile_body(locale="xx-YY")),
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_profile_patch_preserves_other_fields(auth_client, auth_headers):
    auth_client.post("/api/v1/me/onboarding", json=onboarding_body(), headers=auth_headers)

    response = auth_client.patch(
        "/api/v1/me/profile",
        json={"weight_kg": 80.5},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    profile = response.json()["profile"]
    assert profile["weight_kg"] == 80.5
    assert profile["height_cm"] == 175
    assert profile["goal"] == "muscle_gain"

    empty = auth_client.patch("/api/v1/me/profile", json={}, headers=auth_headers)
    assert empty.status_code == 422

    invalid = auth_client.patch(
        "/api/v1/me/profile",
        json={"timezone": "Nowhere/Here"},
        headers=auth_headers,
    )
    assert invalid.status_code == 422


@pytest.mark.integration
def test_equipment_and_injury_replacement(auth_client, auth_headers):
    auth_client.post("/api/v1/me/onboarding", json=onboarding_body(), headers=auth_headers)

    response = auth_client.put(
        "/api/v1/me/equipment",
        json={"equipment": ["barbell"]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["equipment"] == ["barbell"]

    response = auth_client.put(
        "/api/v1/me/equipment",
        json={"equipment": []},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["equipment"] == []

    response = auth_client.put(
        "/api/v1/me/injuries",
        json={"injuries": ["shoulder"]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["injuries"][0]["term"] == "shoulder"

    revoke = auth_client.post(
        "/api/v1/me/consents",
        json={"kind": "health_data_processing", "granted": False},
        headers=auth_headers,
    )
    assert revoke.status_code == 200
    assert revoke.json()["active"]["health_data_processing"] is False

    profile = auth_client.get("/api/v1/me/profile", headers=auth_headers).json()
    assert profile["injuries"] == []

    blocked = auth_client.put(
        "/api/v1/me/injuries",
        json={"injuries": ["knee"]},
        headers=auth_headers,
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "consent_required"


@pytest.mark.integration
def test_consent_version_mismatch_is_rejected(auth_client, auth_headers):
    response = auth_client.post(
        "/api/v1/me/consents",
        json={
            "kind": "research_analytics",
            "granted": True,
            "version": "1999-01",
        },
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"

    response = auth_client.post(
        "/api/v1/me/consents",
        json={
            "kind": "research_analytics",
            "granted": True,
            "version": "2026-01",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["active"]["research_analytics"] is True


@pytest.mark.integration
def test_export_contains_only_own_data(auth_client, token_factory):
    headers_a = {"Authorization": f"Bearer {token_factory('alice')}"}
    headers_b = {"Authorization": f"Bearer {token_factory('bob')}"}

    auth_client.post(
        "/api/v1/me/onboarding",
        json=onboarding_body(injuries=["knee pain"]),
        headers=headers_a,
    )
    auth_client.post(
        "/api/v1/me/onboarding",
        json=onboarding_body(injuries=["shoulder pain"]),
        headers=headers_b,
    )

    response = auth_client.get("/api/v1/me/export", headers=headers_a)
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    body = response.json()

    assert body["schema_version"] == "p0.1"
    assert body["user"]["email"] == "alice@example.com"
    assert [item["term"] for item in body["injuries"]] == ["knee"]
    serialized = json.dumps(body)
    assert "bob@example.com" not in serialized
    assert "shoulder" not in serialized


@pytest.mark.integration
def test_delete_request_schedules_deletion_and_blocks_access(
    auth_client, auth_headers, db_session
):
    auth_client.post("/api/v1/me/onboarding", json=onboarding_body(), headers=auth_headers)

    response = auth_client.delete("/api/v1/me", headers=auth_headers)
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "pending"
    requested_at = datetime.fromisoformat(body["requested_at"].replace("Z", "+00:00"))
    scheduled_for = datetime.fromisoformat(body["scheduled_for"].replace("Z", "+00:00"))
    assert 29 <= (scheduled_for - requested_at).days <= 31

    user = db_session.scalar(select(User))
    assert user is not None
    assert user.deletion_requested_at is not None

    blocked = auth_client.get("/api/v1/me", headers=auth_headers)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "account_deletion_pending"

    actions = set(db_session.scalars(select(AuditLog.action)).all())
    assert "account.deletion_requested" in actions


@pytest.mark.integration
def test_audit_metadata_has_no_pii(auth_client, auth_headers, db_session):
    auth_client.post("/api/v1/me/onboarding", json=onboarding_body(), headers=auth_headers)
    auth_client.get("/api/v1/me/export", headers=auth_headers)

    rows = list(db_session.scalars(select(AuditLog)).all())
    assert rows
    serialized = json.dumps([row.metadata_json for row in rows])
    assert "knee" not in serialized.lower()
    assert "user-1@example.com" not in serialized
    assert "Ridwan" not in serialized

    actions = {row.action for row in rows}
    assert "profile.onboarding_completed" in actions
    assert "account.exported" in actions


@pytest.mark.integration
def test_recommendation_stays_public_when_auth_is_enabled(auth_client, valid_payload):
    response = auth_client.post("/api/v1/recommendation/", json=valid_payload)
    assert response.status_code == 201, response.text
    assert response.json()["days"]


@pytest.mark.integration
def test_openapi_documents_me_and_bearer(auth_client):
    document = auth_client.get("/openapi.json").json()
    paths = document["paths"]
    assert "/api/v1/me" in paths
    assert "/api/v1/me/onboarding" in paths
    assert "/api/v1/me/profile" in paths
    assert "/api/v1/me/consents" in paths
    assert "/api/v1/me/export" in paths
    assert "OIDCBearer" in document["components"]["securitySchemes"]


@pytest.mark.integration
def test_database_not_configured_returns_503(dataset_path, token_factory):
    settings = Settings(
        environment="test",
        dataset_path=dataset_path,
        rate_limit_enabled=False,
        metrics_enabled=False,
        auth_enabled=True,
        auth_profiles_enabled=True,
        auth_dev_mode=True,
        auth_dev_secret=SECRET,
        auth_issuer=ISSUER,
        auth_audience=AUDIENCE,
    )
    app = create_app(settings)
    token = token_factory()

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_not_configured"
