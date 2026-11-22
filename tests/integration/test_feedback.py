"""Integration tests for P0.4 feedback, safety, and admin triage."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import AuditLog, Feedback, UnsafeReport, User, UserRole
from app.main import create_app

SECRET = "test-secret-" + ("x" * 40)
ISSUER = "https://issuer.test"
AUDIENCE = "fitness-api-test"


@pytest.fixture()
def feedback_settings(dataset_path: Path, tmp_path: Path) -> Settings:
    database_path = (tmp_path / "feedback.db").as_posix()
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
        feedback_rate_limit_per_hour=2,
        safety_report_rate_limit_per_hour=2,
        auth_dev_mode=True,
        auth_dev_secret=SECRET,
        auth_issuer=ISSUER,
        auth_audience=AUDIENCE,
    )


@pytest.fixture()
def feedback_app(feedback_settings: Settings):
    return create_app(feedback_settings)


@pytest.fixture()
def feedback_client(feedback_app):
    with TestClient(feedback_app) as client:
        yield client


@pytest.fixture()
def db_session(feedback_client, feedback_app) -> Session:
    session = feedback_app.state.session_factory()
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
                "name": f"User {sub}",
            },
            SECRET,
            algorithm="HS256",
        )

    return make_token


@pytest.fixture()
def auth_headers(token_factory) -> dict:
    return {"Authorization": f"Bearer {token_factory()}"}


def recommendation_body(**overrides) -> dict:
    body = {
        "gender": "male",
        "height_cm": 175,
        "weight_kg": 72,
        "injuries": [],
        "available_days": 2,
        "preferred_body_part": [],
        "preferred_equipment": [],
        "seed": 42,
    }
    body.update(overrides)
    return body


def create_plan(client, headers, *, key: str = "feedback-plan-1"):
    return client.post(
        "/api/v1/plans",
        json={
            "recommendation": recommendation_body(),
            "title": "Feedback Plan",
        },
        headers={**headers, "Idempotency-Key": key},
    )


def start_workout(client, headers, plan_id: str, *, key: str | None = None):
    payload = {"plan_id": plan_id, "day": 1, "timezone": "Asia/Jakarta"}
    if key:
        payload["client_session_id"] = key
    return client.post("/api/v1/workouts/start", json=payload, headers=headers)


def make_admin(client, db_session: Session, token_factory) -> dict:
    headers = {"Authorization": f"Bearer {token_factory('admin-user')}"}
    client.get("/api/v1/me", headers=headers)
    user = db_session.scalar(select(User).where(User.auth_subject == "admin-user"))
    assert user is not None
    db_session.add(UserRole(user_id=user.id, role="platform_admin"))
    db_session.commit()
    return headers


def count(session: Session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


@pytest.mark.integration
def test_feedback_and_safety_are_feature_flagged(client):
    assert client.post("/api/v1/feedback", json={"comment": "hello"}).status_code == 404
    assert client.get("/api/v1/admin/safety-reports").status_code == 404


@pytest.mark.integration
def test_submit_feedback_for_plan_and_workout(
    feedback_client,
    auth_headers,
    db_session,
    token_factory,
):
    plan = create_plan(feedback_client, auth_headers).json()
    workout = start_workout(
        feedback_client,
        auth_headers,
        plan["id"],
        key=str(uuid.uuid4()),
    ).json()

    response = feedback_client.post(
        "/api/v1/feedback",
        json={
            "plan_id": plan["id"],
            "workout_session_id": workout["id"],
            "rating": 4,
            "difficulty": "just_right",
            "pain": False,
            "comment": "good session",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["rating"] == 4
    assert body["difficulty"] == "just_right"
    assert body["plan_id"] == plan["id"]
    assert body["plan_version_id"]
    assert body["workout_session_id"] == workout["id"]
    assert count(db_session, Feedback) == 1

    admin_headers = make_admin(feedback_client, db_session, token_factory)
    listing = feedback_client.get("/api/v1/admin/feedback", headers=admin_headers)
    assert listing.status_code == 200
    assert len(listing.json()["items"]) == 1
    assert listing.json()["items"][0]["comment"] == "good session"


@pytest.mark.integration
def test_feedback_validation_and_ownership(feedback_client, auth_headers, token_factory):
    empty = feedback_client.post("/api/v1/feedback", json={}, headers=auth_headers)
    assert empty.status_code == 422

    invalid_rating = feedback_client.post(
        "/api/v1/feedback",
        json={"rating": 6},
        headers=auth_headers,
    )
    assert invalid_rating.status_code == 422

    other_headers = {"Authorization": f"Bearer {token_factory('other-user')}"}
    plan = create_plan(feedback_client, other_headers, key="other-plan").json()
    not_owned = feedback_client.post(
        "/api/v1/feedback",
        json={"plan_id": plan["id"], "rating": 3},
        headers=auth_headers,
    )
    assert not_owned.status_code == 422
    assert not_owned.json()["error"]["code"] == "feedback_invalid"


@pytest.mark.integration
def test_feedback_rate_limit(feedback_client, auth_headers):
    for index in range(2):
        response = feedback_client.post(
            "/api/v1/feedback",
            json={"comment": f"feedback {index}"},
            headers=auth_headers,
        )
        assert response.status_code == 201

    blocked = feedback_client.post(
        "/api/v1/feedback",
        json={"comment": "third"},
        headers=auth_headers,
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limit_exceeded"


@pytest.mark.integration
def test_safety_report_from_plan_exercise(feedback_client, auth_headers, db_session):
    plan = create_plan(feedback_client, auth_headers).json()
    exercise = plan["days"][0]["exercises"][0]

    response = feedback_client.post(
        "/api/v1/safety-reports",
        json={
            "plan_id": plan["id"],
            "plan_exercise_id": exercise["id"],
            "reason": "sharp pain in the shoulder",
            "severity": "high",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    report = response.json()
    assert report["exercise_id"] == exercise["exercise_id"]
    assert report["exercise_name"] == exercise["exercise_name"]
    assert report["status"] == "open"
    assert report["severity"] == "high"
    assert count(db_session, UnsafeReport) == 1

    actions = set(db_session.scalars(select(AuditLog.action)).all())
    assert "safety_report.created" in actions


@pytest.mark.integration
def test_safety_report_from_workout_and_validation(feedback_client, auth_headers):
    plan = create_plan(feedback_client, auth_headers).json()
    workout = start_workout(
        feedback_client,
        auth_headers,
        plan["id"],
        key=str(uuid.uuid4()),
    ).json()
    exercise = workout["exercises"][0]

    response = feedback_client.post(
        "/api/v1/safety-reports",
        json={
            "workout_session_id": workout["id"],
            "exercise_id": exercise["exercise_id"],
            "reason": "felt unstable during the movement",
            "severity": "medium",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["workout_session_id"] == workout["id"]

    unknown = feedback_client.post(
        "/api/v1/safety-reports",
        json={
            "exercise_id": "not-in-dataset",
            "reason": "this exercise is unsafe",
        },
        headers=auth_headers,
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "safety_report_invalid"


@pytest.mark.integration
def test_safety_report_rate_limit(feedback_client, auth_headers):
    plan = create_plan(feedback_client, auth_headers).json()
    exercise = plan["days"][0]["exercises"][0]

    for index in range(2):
        response = feedback_client.post(
            "/api/v1/safety-reports",
            json={
                "plan_id": plan["id"],
                "plan_exercise_id": exercise["id"],
                "reason": f"unsafe reason {index}",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201

    blocked = feedback_client.post(
        "/api/v1/safety-reports",
        json={
            "plan_id": plan["id"],
            "plan_exercise_id": exercise["id"],
            "reason": "third report",
        },
        headers=auth_headers,
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limit_exceeded"


@pytest.mark.integration
def test_admin_requires_platform_admin(
    feedback_client,
    auth_headers,
    db_session,
    token_factory,
):
    plan = create_plan(feedback_client, auth_headers).json()
    exercise = plan["days"][0]["exercises"][0]
    feedback_client.post(
        "/api/v1/safety-reports",
        json={
            "plan_id": plan["id"],
            "plan_exercise_id": exercise["id"],
            "reason": "unsafe movement",
        },
        headers=auth_headers,
    )

    forbidden = feedback_client.get("/api/v1/admin/safety-reports", headers=auth_headers)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"

    admin_headers = make_admin(feedback_client, db_session, token_factory)
    allowed = feedback_client.get("/api/v1/admin/safety-reports", headers=admin_headers)
    assert allowed.status_code == 200
    assert len(allowed.json()["items"]) == 1


@pytest.mark.integration
def test_admin_triage_transitions_and_audit(
    feedback_client,
    auth_headers,
    db_session,
    token_factory,
):
    plan = create_plan(feedback_client, auth_headers).json()
    exercise = plan["days"][0]["exercises"][0]
    report = feedback_client.post(
        "/api/v1/safety-reports",
        json={
            "plan_id": plan["id"],
            "plan_exercise_id": exercise["id"],
            "reason": "pain during overhead press",
            "severity": "medium",
        },
        headers=auth_headers,
    ).json()
    admin_headers = make_admin(feedback_client, db_session, token_factory)

    triaged = feedback_client.patch(
        f"/api/v1/admin/safety-reports/{report['id']}",
        json={
            "status": "triaged",
            "severity": "critical",
            "resolution_note": "reviewing with safety reviewer",
        },
        headers=admin_headers,
    )
    assert triaged.status_code == 200, triaged.text
    assert triaged.json()["status"] == "triaged"
    assert triaged.json()["severity"] == "critical"
    assert triaged.json()["triaged_at"] is not None

    resolved = feedback_client.patch(
        f"/api/v1/admin/safety-reports/{report['id']}",
        json={"status": "resolved", "resolution_note": "exercise relabelled"},
        headers=admin_headers,
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolved_at"] is not None
    assert resolved.json()["resolved_by"] is not None

    invalid = feedback_client.patch(
        f"/api/v1/admin/safety-reports/{report['id']}",
        json={"status": "triaged"},
        headers=admin_headers,
    )
    assert invalid.status_code == 409
    assert invalid.json()["error"]["code"] == "invalid_safety_transition"

    actions = set(db_session.scalars(select(AuditLog.action)).all())
    assert "safety_report.triaged" in actions
    assert "safety_report.resolved" in actions
    assert "safety_report.severity_changed" in actions
    assert "safety_report.note_updated" in actions


@pytest.mark.integration
def test_admin_filters_pagination_and_quality_summary(
    feedback_client,
    auth_headers,
    db_session,
    token_factory,
):
    plan = create_plan(feedback_client, auth_headers).json()
    exercise = plan["days"][0]["exercises"][0]
    feedback_client.post(
        "/api/v1/feedback",
        json={"plan_id": plan["id"], "rating": 5, "comment": "great"},
        headers=auth_headers,
    )
    for severity in ("low", "high"):
        feedback_client.post(
            "/api/v1/safety-reports",
            json={
                "plan_id": plan["id"],
                "plan_exercise_id": exercise["id"],
                "reason": f"{severity} severity report",
                "severity": severity,
            },
            headers=auth_headers,
        )

    admin_headers = make_admin(feedback_client, db_session, token_factory)
    high = feedback_client.get(
        "/api/v1/admin/safety-reports?severity=high",
        headers=admin_headers,
    )
    assert high.status_code == 200
    assert len(high.json()["items"]) == 1
    assert high.json()["items"][0]["severity"] == "high"

    first_page = feedback_client.get(
        "/api/v1/admin/safety-reports?limit=1",
        headers=admin_headers,
    ).json()
    assert len(first_page["items"]) == 1
    assert first_page["next_cursor"]
    second_page = feedback_client.get(
        f"/api/v1/admin/safety-reports?limit=1&cursor={first_page['next_cursor']}",
        headers=admin_headers,
    ).json()
    assert len(second_page["items"]) == 1

    summary = feedback_client.get(
        "/api/v1/admin/quality-summary",
        headers=admin_headers,
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["total_plans"] == 1
    assert body["total_feedback"] == 1
    assert body["average_rating"] == 5.0
    assert body["reports_total"] == 2
    assert body["reports_by_severity"]["high"] == 1
    assert body["reports_per_1000_plans"] == 2000.0

    audit = feedback_client.get(
        "/api/v1/admin/audit?action=feedback.submitted",
        headers=admin_headers,
    )
    assert audit.status_code == 200
    assert len(audit.json()["items"]) == 1


@pytest.mark.integration
def test_audit_metadata_has_no_feedback_health_text(
    feedback_client,
    auth_headers,
    db_session,
    token_factory,
):
    plan = create_plan(feedback_client, auth_headers).json()
    exercise = plan["days"][0]["exercises"][0]
    feedback_client.post(
        "/api/v1/feedback",
        json={
            "plan_id": plan["id"],
            "rating": 2,
            "pain": True,
            "pain_area": "left shoulder",
            "comment": "private shoulder comment",
        },
        headers=auth_headers,
    )
    feedback_client.post(
        "/api/v1/safety-reports",
        json={
            "plan_id": plan["id"],
            "plan_exercise_id": exercise["id"],
            "reason": "private unsafe reason",
            "severity": "high",
        },
        headers=auth_headers,
    )
    admin_headers = make_admin(feedback_client, db_session, token_factory)
    report = feedback_client.get(
        "/api/v1/admin/safety-reports",
        headers=admin_headers,
    ).json()["items"][0]
    feedback_client.patch(
        f"/api/v1/admin/safety-reports/{report['id']}",
        json={"status": "resolved", "resolution_note": "private resolution note"},
        headers=admin_headers,
    )

    serialized = " ".join(
        str(entry.metadata_json)
        for entry in db_session.scalars(select(AuditLog)).all()
    )
    assert "private shoulder comment" not in serialized
    assert "left shoulder" not in serialized
    assert "private unsafe reason" not in serialized
    assert "private resolution note" not in serialized
    assert "user-1@example.com" not in serialized


@pytest.mark.integration
def test_critical_report_triggers_alert(
    feedback_client,
    auth_headers,
    monkeypatch,
):
    calls = []

    def fake_alert(report, webhook_url):
        calls.append((str(report.id), webhook_url))

    monkeypatch.setattr(
        "app.services.feedback.send_critical_alert",
        fake_alert,
    )
    plan = create_plan(feedback_client, auth_headers).json()
    exercise = plan["days"][0]["exercises"][0]
    response = feedback_client.post(
        "/api/v1/safety-reports",
        json={
            "plan_id": plan["id"],
            "plan_exercise_id": exercise["id"],
            "reason": "critical safety issue",
            "severity": "critical",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert len(calls) == 1
    assert calls[0][0] == response.json()["id"]


@pytest.mark.integration
def test_feedback_openapi(feedback_client):
    document = feedback_client.get("/openapi.json").json()
    paths = document["paths"]
    assert "/api/v1/feedback" in paths
    assert "/api/v1/safety-reports" in paths
    assert "/api/v1/admin/safety-reports" in paths
    assert "/api/v1/admin/safety-reports/{report_id}" in paths
    assert "/api/v1/admin/feedback" in paths
    assert "/api/v1/admin/audit" in paths
    assert "/api/v1/admin/quality-summary" in paths
