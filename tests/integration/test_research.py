"""Integration tests for P2.2 research, experimentation, and quality."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_settings as deps_get_settings
from app.core.config import Settings
from app.db.models import (
    AuditLog,
    ExperimentAssignment,
    PlanVersion,
    ResearchEvent,
    ResearchVersion,
    User,
    UserRole,
)
from app.main import create_app

SECRET = "test-secret-" + ("x" * 40)
ISSUER = "https://issuer.test"
AUDIENCE = "fitness-api-test"
EXPORT_SECRET = "research-export-secret-" + ("y" * 20)


@pytest.fixture()
def research_settings(dataset_path: Path, tmp_path: Path) -> Settings:
    database_path = (tmp_path / "research.db").as_posix()
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
        feedback_rate_limit_per_hour=20,
        safety_report_rate_limit_per_hour=20,
        research_enabled=True,
        research_export_secret=EXPORT_SECRET,
        research_event_rate_limit_per_hour=5,
        auth_dev_mode=True,
        auth_dev_secret=SECRET,
        auth_issuer=ISSUER,
        auth_audience=AUDIENCE,
    )


@pytest.fixture()
def research_app(research_settings: Settings):
    return create_app(research_settings)


@pytest.fixture()
def research_client(research_app):
    with TestClient(research_app) as client:
        yield client


@pytest.fixture()
def db_session(research_client, research_app) -> Session:
    session = research_app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def token_factory():
    def make_token(sub: str, email: str | None = None) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": sub,
                "iss": ISSUER,
                "aud": AUDIENCE,
                "iat": now,
                "exp": now + timedelta(minutes=10),
                "email": email or f"{sub}@example.com",
                "emailVerified": True,
                "name": sub,
            },
            SECRET,
            algorithm="HS256",
        )

    return make_token


@pytest.fixture()
def auth_headers(research_client, token_factory) -> dict:
    return headers_for(research_client, token_factory, "user-1")


def headers_for(client, token_factory, sub: str) -> dict:
    headers = {"Authorization": f"Bearer {token_factory(sub)}"}
    assert client.get("/api/v1/me", headers=headers).status_code == 200
    return headers


def make_admin(client, db_session: Session, token_factory, sub: str = "admin-1") -> dict:
    headers = headers_for(client, token_factory, sub)
    user = db_session.scalar(select(User).where(User.auth_subject == sub))
    assert user is not None
    db_session.add(UserRole(user_id=user.id, role="platform_admin"))
    db_session.commit()
    return headers


def grant_research_consent(client, headers, *, granted: bool = True) -> None:
    response = client.post(
        "/api/v1/me/consents",
        json={
            "kind": "research_analytics",
            "granted": granted,
            "version": "2026-01",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text


def recommendation_body() -> dict:
    return {
        "gender": "male",
        "height_cm": 175,
        "weight_kg": 72,
        "injuries": [],
        "available_days": 2,
        "preferred_body_part": [],
        "preferred_equipment": [],
        "seed": 42,
    }


def create_plan(client, headers, key: str = "research-plan-1"):
    return client.post(
        "/api/v1/plans",
        json={"recommendation": recommendation_body(), "title": "Secret Plan"},
        headers={**headers, "Idempotency-Key": key},
    )


def start_workout(client, headers, plan_id: str, key: str | None = None):
    return client.post(
        "/api/v1/workouts/start",
        json={
            "plan_id": plan_id,
            "day": 1,
            "timezone": "Asia/Jakarta",
            **({"client_session_id": key} if key else {}),
        },
        headers=headers,
    )


def create_experiment(
    client,
    admin_headers,
    *,
    key: str = "checkout-test",
    status: str = "running",
    traffic: int = 100,
):
    return client.post(
        "/api/v1/admin/experiments",
        json={
            "key": key,
            "name": key,
            "description": "research experiment",
            "status": status,
            "traffic_percent": traffic,
            "variants": [
                {"key": "control", "weight": 50},
                {"key": "treatment", "weight": 50},
            ],
        },
        headers=admin_headers,
    )


def report_window():
    now = datetime.now(UTC)
    return (now - timedelta(hours=1)).isoformat(), (now + timedelta(hours=1)).isoformat()


def count(session: Session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


@pytest.mark.integration
def test_research_is_feature_flagged(client):
    assert client.post("/api/v1/me/events", json={"name": "app_opened"}).status_code == 404
    assert client.get("/api/v1/admin/research/versions").status_code == 404
    assert client.get("/api/v1/me/experiments").status_code == 404


@pytest.mark.integration
def test_event_requires_consent_and_validates(research_client, auth_headers):
    blocked = research_client.post(
        "/api/v1/me/events",
        json={"name": "app_opened"},
        headers=auth_headers,
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "research_consent_required"

    grant_research_consent(research_client, auth_headers)

    unknown = research_client.post(
        "/api/v1/me/events",
        json={"name": "arbitrary_event"},
        headers=auth_headers,
    )
    assert unknown.status_code == 422

    sensitive = research_client.post(
        "/api/v1/me/events",
        json={"name": "app_opened", "properties": {"email": "a@b.com"}},
        headers=auth_headers,
    )
    assert sensitive.status_code == 422

    nested = research_client.post(
        "/api/v1/me/events",
        json={"name": "app_opened", "properties": {"bucket": {"nested": 1}}},
        headers=auth_headers,
    )
    assert nested.status_code == 422

    future = research_client.post(
        "/api/v1/me/events",
        json={
            "name": "app_opened",
            "occurred_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers,
    )
    assert future.status_code == 422

    valid = research_client.post(
        "/api/v1/me/events",
        json={
            "name": "plan_generated",
            "properties": {"surface": "mobile", "duration_bucket": "1_5m", "ok": True},
        },
        headers=auth_headers,
    )
    assert valid.status_code == 201, valid.text
    body = valid.json()
    assert body["properties"]["surface"] == "mobile"


@pytest.mark.integration
def test_event_idempotency_and_rate_limit(
    research_client, auth_headers, db_session
):
    grant_research_consent(research_client, auth_headers)
    first = research_client.post(
        "/api/v1/me/events",
        json={"name": "app_opened", "idempotency_key": "event-key-1"},
        headers=auth_headers,
    )
    assert first.status_code == 201
    replay = research_client.post(
        "/api/v1/me/events",
        json={"name": "app_opened", "idempotency_key": "event-key-1"},
        headers=auth_headers,
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert count(db_session, ResearchEvent) == 1

    for index in range(4):
        response = research_client.post(
            "/api/v1/me/events",
            json={"name": "workout_started", "idempotency_key": f"extra-{index}"},
            headers=auth_headers,
        )
        assert response.status_code == 201

    blocked = research_client.post(
        "/api/v1/me/events",
        json={"name": "workout_started"},
        headers=auth_headers,
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limit_exceeded"


@pytest.mark.integration
def test_experiment_assignment_is_deterministic_and_consent_gated(
    research_client, auth_headers, db_session, token_factory
):
    admin_headers = make_admin(research_client, db_session, token_factory)
    created = create_experiment(research_client, admin_headers)
    assert created.status_code == 201, created.text

    without_consent = research_client.get(
        "/api/v1/me/experiments", headers=auth_headers
    )
    assert without_consent.status_code == 200
    assert without_consent.json()["items"] == []

    grant_research_consent(research_client, auth_headers)
    first = research_client.get("/api/v1/me/experiments", headers=auth_headers)
    assert first.status_code == 200
    items = first.json()["items"]
    assert len(items) == 1
    assert items[0]["experiment_key"] == "checkout-test"
    assert items[0]["variant"] in {"control", "treatment"}
    assert items[0]["exposed_at"] is not None

    second = research_client.get("/api/v1/me/experiments", headers=auth_headers)
    assert second.json()["items"][0]["variant"] == items[0]["variant"]
    assert count(db_session, ExperimentAssignment) == 1


@pytest.mark.integration
def test_experiment_admin_validation_and_pause(
    research_client, auth_headers, db_session, token_factory
):
    admin_headers = make_admin(research_client, db_session, token_factory)

    forbidden = research_client.post(
        "/api/v1/admin/experiments",
        json={
            "key": "forbidden-test",
            "name": "Forbidden",
            "variants": [
                {"key": "a", "weight": 50},
                {"key": "b", "weight": 50},
            ],
        },
        headers=auth_headers,
    )
    assert forbidden.status_code == 403

    invalid = research_client.post(
        "/api/v1/admin/experiments",
        json={
            "key": "single-variant",
            "name": "Single",
            "variants": [{"key": "only", "weight": 100}],
        },
        headers=admin_headers,
    )
    assert invalid.status_code == 422

    created = create_experiment(research_client, admin_headers)
    assert created.status_code == 201
    experiment = created.json()
    duplicate = create_experiment(research_client, admin_headers)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "experiment_conflict"

    listed = research_client.get(
        "/api/v1/admin/experiments", headers=admin_headers
    )
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1

    grant_research_consent(research_client, auth_headers)
    assert len(
        research_client.get("/api/v1/me/experiments", headers=auth_headers).json()[
            "items"
        ]
    ) == 1

    paused = research_client.patch(
        f"/api/v1/admin/experiments/{experiment['id']}",
        json={"status": "paused"},
        headers=admin_headers,
    )
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    assert (
        research_client.get("/api/v1/me/experiments", headers=auth_headers).json()[
            "items"
        ]
        == []
    )

    resumed = research_client.patch(
        f"/api/v1/admin/experiments/{experiment['id']}",
        json={"status": "running"},
        headers=admin_headers,
    )
    assert resumed.status_code == 200
    resumed_items = research_client.get(
        "/api/v1/me/experiments", headers=auth_headers
    ).json()["items"]
    assert len(resumed_items) == 1
    assert resumed_items[0]["variant"] in {"control", "treatment"}
    assert count(db_session, ExperimentAssignment) == 1


@pytest.mark.integration
def test_experiment_report_counts(
    research_client, auth_headers, db_session, token_factory
):
    admin_headers = make_admin(research_client, db_session, token_factory)
    experiment = create_experiment(research_client, admin_headers).json()
    grant_research_consent(research_client, auth_headers)

    assignment = research_client.get(
        "/api/v1/me/experiments", headers=auth_headers
    ).json()["items"][0]
    research_client.post(
        "/api/v1/me/events",
        json={"name": "workout_started", "idempotency_key": "exp-event-1"},
        headers=auth_headers,
    )
    research_client.post(
        "/api/v1/me/events",
        json={"name": "workout_completed", "idempotency_key": "exp-event-2"},
        headers=auth_headers,
    )

    report = research_client.get(
        f"/api/v1/admin/experiments/{experiment['id']}",
        headers=admin_headers,
    )
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["assignments_total"] == 1
    assert body["exposures_total"] == 1
    assert body["variant_weights"] == {"control": 50, "treatment": 50}
    variant = next(
        item for item in body["by_variant"] if item["variant"] == assignment["variant"]
    )
    assert variant["assignments"] == 1
    assert variant["exposures"] == 1
    assert variant["events"]["workout_started"] == 1
    assert variant["events"]["workout_completed"] == 1


@pytest.mark.integration
def test_version_registry(
    research_client, auth_headers, db_session, token_factory
):
    admin_headers = make_admin(research_client, db_session, token_factory)
    forbidden = research_client.post(
        "/api/v1/admin/research/versions/register",
        headers=auth_headers,
    )
    assert forbidden.status_code == 403

    registered = research_client.post(
        "/api/v1/admin/research/versions/register",
        headers=admin_headers,
    )
    assert registered.status_code == 200, registered.text
    items = registered.json()["items"]
    assert {item["kind"] for item in items} == {"dataset", "algorithm"}
    dataset = next(item for item in items if item["kind"] == "dataset")
    assert dataset["row_count"] == 222
    assert len(dataset["checksum"]) == 64
    assert dataset["metadata"]["exercise_count"] == 222

    replay = research_client.post(
        "/api/v1/admin/research/versions/register",
        headers=admin_headers,
    )
    assert replay.status_code == 200
    assert {item["id"] for item in replay.json()["items"]} == {
        item["id"] for item in items
    }
    assert count(db_session, ResearchVersion) == 2

    listed = research_client.get(
        "/api/v1/admin/research/versions?kind=dataset",
        headers=admin_headers,
    )
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1


@pytest.mark.integration
def test_quality_reviews_for_versions_and_plan(
    research_client, auth_headers, db_session, token_factory
):
    admin_headers = make_admin(research_client, db_session, token_factory)
    versions = research_client.post(
        "/api/v1/admin/research/versions/register",
        headers=admin_headers,
    ).json()["items"]
    dataset = next(item for item in versions if item["kind"] == "dataset")

    invalid_subject = research_client.post(
        "/api/v1/admin/quality-reviews",
        json={
            "subject_type": "dataset_version",
            "subject_id": "unknown-version",
            "rubric": {"safety": 5},
        },
        headers=admin_headers,
    )
    assert invalid_subject.status_code == 422
    assert invalid_subject.json()["error"]["code"] == "quality_review_invalid"

    invalid_rubric = research_client.post(
        "/api/v1/admin/quality-reviews",
        json={
            "subject_type": "dataset_version",
            "subject_id": dataset["version"],
            "rubric": {"unknown": 5},
        },
        headers=admin_headers,
    )
    assert invalid_rubric.status_code == 422

    created = research_client.post(
        "/api/v1/admin/quality-reviews",
        json={
            "subject_type": "dataset_version",
            "subject_id": dataset["version"],
            "rubric": {"safety": 5, "variety": 4, "clarity": 4},
            "notes": "expert notes must stay private",
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    review = created.json()
    assert review["status"] == "pending"

    updated = research_client.patch(
        f"/api/v1/admin/quality-reviews/{review['id']}",
        json={"status": "approved", "notes": "approved after review"},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "approved"

    listed = research_client.get(
        "/api/v1/admin/quality-reviews?status=approved",
        headers=admin_headers,
    )
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1
    assert (
        research_client.get(
            f"/api/v1/admin/quality-reviews/{review['id']}",
            headers=admin_headers,
        ).json()["notes"]
        == "approved after review"
    )

    plan = create_plan(research_client, auth_headers).json()
    plan_version = db_session.scalar(
        select(PlanVersion).where(PlanVersion.plan_id == uuid.UUID(plan["id"]))
    )
    assert plan_version is not None
    plan_review = research_client.post(
        "/api/v1/admin/quality-reviews",
        json={
            "subject_type": "plan_version",
            "subject_id": str(plan_version.id),
            "rubric": {"safety": 4, "progression": 4},
        },
        headers=admin_headers,
    )
    assert plan_review.status_code == 201, plan_review.text

    audit_text = " ".join(
        str(row.metadata_json) for row in db_session.scalars(select(AuditLog)).all()
    )
    assert "expert notes must stay private" not in audit_text
    assert "approved after review" not in audit_text


@pytest.mark.integration
def test_research_report_aggregates(
    research_client, auth_headers, db_session, token_factory
):
    admin_headers = make_admin(research_client, db_session, token_factory)
    research_client.post(
        "/api/v1/admin/research/versions/register",
        headers=admin_headers,
    )
    grant_research_consent(research_client, auth_headers)

    plan = create_plan(research_client, auth_headers).json()
    workout = start_workout(research_client, auth_headers, plan["id"]).json()
    completed = research_client.post(
        f"/api/v1/workouts/{workout['id']}/complete",
        json={"notes": "private workout note"},
        headers=auth_headers,
    )
    assert completed.status_code == 200
    feedback = research_client.post(
        "/api/v1/feedback",
        json={
            "plan_id": plan["id"],
            "workout_session_id": workout["id"],
            "rating": 4,
            "difficulty": "just_right",
            "comment": "private feedback comment",
        },
        headers=auth_headers,
    )
    assert feedback.status_code == 201, feedback.text
    exercise = plan["days"][0]["exercises"][0]
    safety = research_client.post(
        "/api/v1/safety-reports",
        json={
            "plan_id": plan["id"],
            "plan_exercise_id": exercise["id"],
            "reason": "private safety reason",
            "severity": "medium",
        },
        headers=auth_headers,
    )
    assert safety.status_code == 201, safety.text
    research_client.post(
        "/api/v1/me/events",
        json={"name": "plan_generated", "properties": {"surface": "web"}},
        headers=auth_headers,
    )

    start, end = report_window()
    report = research_client.get(
        "/api/v1/admin/research/report",
        params={"start": start, "end": end},
        headers=admin_headers,
    )
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["events_total"] == 1
    assert body["events_by_name"] == {"plan_generated": 1}
    assert body["plans_total"] == 1
    assert body["workouts_total"] == 1
    assert body["workouts_completed"] == 1
    assert body["workout_completion_rate"] == 100.0
    assert body["feedback_total"] == 1
    assert body["average_rating"] == 4.0
    assert body["safety_reports_total"] == 1
    assert body["reports_by_severity"] == {"medium": 1}
    assert len(body["versions"]) == 2

    forbidden = research_client.get(
        "/api/v1/admin/research/report",
        params={"start": start, "end": end},
        headers=auth_headers,
    )
    assert forbidden.status_code == 403

    invalid = research_client.get(
        "/api/v1/admin/research/report",
        params={"start": end, "end": start},
        headers=admin_headers,
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "research_range_invalid"

    series = research_client.get(
        "/api/v1/admin/research/report",
        params={"start": start, "end": end},
        headers=admin_headers,
    )
    assert series.json()["generated_at"]


@pytest.mark.integration
def test_research_export_is_pii_redacted_and_consent_gated(
    research_client, auth_headers, db_session, token_factory
):
    admin_headers = make_admin(research_client, db_session, token_factory)
    research_client.post(
        "/api/v1/admin/research/versions/register",
        headers=admin_headers,
    )
    grant_research_consent(research_client, auth_headers)
    plan = create_plan(research_client, auth_headers).json()
    workout = start_workout(research_client, auth_headers, plan["id"]).json()
    research_client.post(
        f"/api/v1/workouts/{workout['id']}/complete",
        json={"notes": "private workout note"},
        headers=auth_headers,
    )
    research_client.post(
        "/api/v1/feedback",
        json={
            "plan_id": plan["id"],
            "workout_session_id": workout["id"],
            "rating": 3,
            "comment": "private feedback comment",
        },
        headers=auth_headers,
    )
    research_client.post(
        "/api/v1/me/events",
        json={"name": "app_opened", "properties": {"surface": "mobile"}},
        headers=auth_headers,
    )

    # A second user without research consent must never appear.
    other_headers = headers_for(research_client, token_factory, "other-1")
    other_plan = create_plan(research_client, other_headers, key="other-plan-1")
    assert other_plan.status_code == 201

    start, end = report_window()
    export = research_client.get(
        "/api/v1/admin/research/export",
        params={"start": start, "end": end},
        headers=admin_headers,
    )
    assert export.status_code == 200, export.text
    body = export.json()
    assert body["user_count"] == 1
    assert len(body["plans"]) == 1
    assert len(body["events"]) == 1
    assert len(body["workouts"]) == 1
    assert len(body["feedback"]) == 1
    assert body["events"][0]["user_ref"].startswith("user_")
    assert body["plans"][0]["plan_ref"].startswith("plan_")
    assert body["workouts"][0]["workout_ref"].startswith("workout_")

    serialized = str(body).lower()
    assert "@example.com" not in serialized
    assert "secret plan" not in serialized
    assert "private workout note" not in serialized
    assert "private feedback comment" not in serialized
    assert "owner_user_id" not in serialized
    assert plan["id"] not in serialized
    assert str(other_plan.json()["id"]) not in serialized
    assert "surface" in serialized

    research_app = research_client.app
    original = research_app.state.settings
    research_app.dependency_overrides[deps_get_settings] = lambda: original.model_copy(
        update={"research_export_secret": None}
    )
    try:
        no_secret = research_client.get(
            "/api/v1/admin/research/export",
            params={"start": start, "end": end},
            headers=admin_headers,
        )
    finally:
        research_app.dependency_overrides.pop(deps_get_settings, None)
    assert no_secret.status_code == 503
    assert no_secret.json()["error"]["code"] == "research_export_not_configured"


@pytest.mark.integration
def test_consent_revocation_hides_research_data(
    research_client, auth_headers, db_session, token_factory
):
    admin_headers = make_admin(research_client, db_session, token_factory)
    create_experiment(research_client, admin_headers)
    grant_research_consent(research_client, auth_headers)
    research_client.post(
        "/api/v1/me/events",
        json={"name": "app_opened"},
        headers=auth_headers,
    )
    assigned = research_client.get(
        "/api/v1/me/experiments", headers=auth_headers
    )
    assert len(assigned.json()["items"]) == 1

    grant_research_consent(research_client, auth_headers, granted=False)
    assert (
        research_client.get("/api/v1/me/experiments", headers=auth_headers).json()[
            "items"
        ]
        == []
    )
    blocked = research_client.post(
        "/api/v1/me/events",
        json={"name": "app_opened"},
        headers=auth_headers,
    )
    assert blocked.status_code == 403

    start, end = report_window()
    report = research_client.get(
        "/api/v1/admin/research/report",
        params={"start": start, "end": end},
        headers=admin_headers,
    )
    assert report.status_code == 200
    assert report.json()["events_total"] == 0


@pytest.mark.integration
def test_research_openapi(research_client):
    document = research_client.get("/openapi.json").json()
    paths = document["paths"]
    assert "/api/v1/me/events" in paths
    assert "/api/v1/me/experiments" in paths
    assert "/api/v1/admin/research/versions/register" in paths
    assert "/api/v1/admin/research/versions" in paths
    assert "/api/v1/admin/research/report" in paths
    assert "/api/v1/admin/research/export" in paths
    assert "/api/v1/admin/experiments" in paths
    assert "/api/v1/admin/experiments/{experiment_id}" in paths
    assert "/api/v1/admin/quality-reviews" in paths
    assert "/api/v1/admin/quality-reviews/{review_id}" in paths
