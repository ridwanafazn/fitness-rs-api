"""Integration tests for P0.2 plan lifecycle."""

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
from app.db.models import (
    AuditLog,
    Plan,
    PlanDay,
    PlanExercise,
    PlanShare,
    PlanVersion,
)
from app.main import create_app

SECRET = "test-secret-" + ("x" * 40)
ISSUER = "https://issuer.test"
AUDIENCE = "fitness-api-test"


@pytest.fixture()
def plan_settings(dataset_path: Path, tmp_path: Path) -> Settings:
    database_path = (tmp_path / "plans.db").as_posix()
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
        plans_enabled=True,
    )


@pytest.fixture()
def plan_app(plan_settings: Settings):
    return create_app(plan_settings)


@pytest.fixture()
def plan_client(plan_app):
    with TestClient(plan_app) as client:
        yield client


@pytest.fixture()
def db_session(plan_client, plan_app) -> Session:
    session = plan_app.state.session_factory()
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


def plan_body(**overrides) -> dict:
    body = {
        "recommendation": recommendation_body(),
        "title": "Test Plan",
    }
    body.update(overrides)
    return body


def create_plan(client, headers, key: str = "plan-key-1", body: dict | None = None):
    return client.post(
        "/api/v1/plans",
        json=body or plan_body(),
        headers={**headers, "Idempotency-Key": key},
    )


def count(session: Session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


@pytest.mark.integration
def test_plans_are_feature_flagged(client):
    response = client.get("/api/v1/plans")
    assert response.status_code == 404


@pytest.mark.integration
def test_create_generated_plan(plan_client, auth_headers, db_session):
    response = create_plan(plan_client, auth_headers)
    assert response.status_code == 201, response.text
    plan = response.json()

    assert plan["title"] == "Test Plan"
    assert plan["status"] == "active"
    assert plan["current_version"] == 1
    assert plan["revision"] == 1
    assert plan["split_type"]
    assert len(plan["days"]) == 2
    assert plan["seed"] == 42
    assert plan["input"]["available_days"] == 2
    assert plan["bmi"] > 0
    assert plan["days"][0]["exercises"]
    assert plan["days"][0]["exercises"][0]["exercise_image"]

    assert count(db_session, Plan) == 1
    assert count(db_session, PlanVersion) == 1
    assert count(db_session, PlanDay) == 2
    assert count(db_session, PlanExercise) > 2


@pytest.mark.integration
def test_create_requires_idempotency_key(plan_client, auth_headers):
    response = plan_client.post(
        "/api/v1/plans",
        json=plan_body(),
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_idempotency_key_replays_same_plan(plan_client, auth_headers):
    first = create_plan(plan_client, auth_headers, key="same-key")
    second = create_plan(plan_client, auth_headers, key="same-key")
    third = create_plan(plan_client, auth_headers, key="other-key")

    assert first.status_code == 201
    assert second.status_code == 201
    assert third.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert third.json()["id"] != first.json()["id"]

    conflict = create_plan(
        plan_client,
        auth_headers,
        key="same-key",
        body=plan_body(title="Different title"),
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"


@pytest.mark.integration
def test_import_recommendation_result(plan_client, auth_headers):
    rec_payload = recommendation_body(available_days=1, preferred_body_part=["chest"])
    recommendation = plan_client.post(
        "/api/v1/recommendation/",
        json=rec_payload,
    )
    assert recommendation.status_code == 201
    result = recommendation.json()

    response = plan_client.post(
        "/api/v1/plans/import",
        json={
            "recommendation": rec_payload,
            "result": result,
            "title": "Imported Plan",
        },
        headers={**auth_headers, "Idempotency-Key": "import-key"},
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["title"] == "Imported Plan"
    assert [day["day"] for day in plan["days"]] == [1]
    assert plan["days"][0]["exercises"][0]["exercise_id"] == result["days"][0]["exercises"][0][
        "exercise_id"
    ]

    mismatch = dict(result)
    mismatch["dataset_version"] = "deadbeefdeadbeef"
    response = plan_client.post(
        "/api/v1/plans/import",
        json={
            "recommendation": rec_payload,
            "result": mismatch,
        },
        headers={**auth_headers, "Idempotency-Key": "import-mismatch"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "plan_dataset_mismatch"

    first_body_part = result["days"][0]["exercises"][0]["body_part"]
    unsafe_recommendation = dict(rec_payload)
    unsafe_recommendation["injuries"] = [first_body_part]
    response = plan_client.post(
        "/api/v1/plans/import",
        json={
            "recommendation": unsafe_recommendation,
            "result": result,
        },
        headers={**auth_headers, "Idempotency-Key": "import-unsafe"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "plan_invalid"


@pytest.mark.integration
def test_plan_ownership_and_versions(plan_client, token_factory):
    alice = {"Authorization": f"Bearer {token_factory('alice')}"}
    bob = {"Authorization": f"Bearer {token_factory('bob')}"}

    created = create_plan(plan_client, alice, key="alice-plan")
    plan_id = created.json()["id"]

    assert plan_client.get(f"/api/v1/plans/{plan_id}", headers=alice).status_code == 200
    assert plan_client.get(f"/api/v1/plans/{plan_id}", headers=bob).status_code == 404

    alice_list = plan_client.get("/api/v1/plans", headers=alice)
    bob_list = plan_client.get("/api/v1/plans", headers=bob)
    assert len(alice_list.json()["items"]) == 1
    assert bob_list.json()["items"] == []

    versions = plan_client.get(f"/api/v1/plans/{plan_id}/versions", headers=alice)
    assert versions.status_code == 200
    assert [item["version"] for item in versions.json()["items"]] == [1]
    assert plan_client.get(f"/api/v1/plans/{plan_id}/versions", headers=bob).status_code == 404


@pytest.mark.integration
def test_lock_creates_immutable_new_version(plan_client, auth_headers, db_session):
    created = create_plan(plan_client, auth_headers).json()
    plan_id = created["id"]
    first = created["days"][0]["exercises"][0]

    response = plan_client.patch(
        f"/api/v1/plans/{plan_id}",
        json={
            "action": "lock",
            "expected_revision": 1,
            "plan_exercise_id": first["id"],
            "locked": True,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["current_version"] == 2
    assert plan["revision"] == 2
    assert plan["days"][0]["exercises"][0]["locked"] is True

    versions = plan_client.get(f"/api/v1/plans/{plan_id}/versions", headers=auth_headers)
    assert [item["version"] for item in versions.json()["items"]] == [2, 1]

    old_version = db_session.scalar(
        select(PlanVersion).where(
            PlanVersion.plan_id == uuid.UUID(plan_id),
            PlanVersion.version == 1,
        )
    )
    assert old_version is not None
    old_exercise = db_session.scalar(
        select(PlanExercise)
        .join(PlanDay, PlanExercise.plan_day_id == PlanDay.id)
        .where(
            PlanDay.plan_version_id == old_version.id,
            PlanExercise.exercise_id == first["exercise_id"],
        )
    )
    assert old_exercise is not None
    assert old_exercise.locked is False


@pytest.mark.integration
def test_swap_requires_unlock_and_changes_exercise(plan_client, auth_headers):
    created = create_plan(plan_client, auth_headers).json()
    plan_id = created["id"]
    first = created["days"][0]["exercises"][0]

    lock = plan_client.patch(
        f"/api/v1/plans/{plan_id}",
        json={
            "action": "lock",
            "expected_revision": 1,
            "plan_exercise_id": first["id"],
            "locked": True,
        },
        headers=auth_headers,
    )
    assert lock.status_code == 200
    locked_exercise = lock.json()["days"][0]["exercises"][0]

    blocked = plan_client.patch(
        f"/api/v1/plans/{plan_id}",
        json={
            "action": "swap",
            "expected_revision": 2,
            "plan_exercise_id": locked_exercise["id"],
        },
        headers=auth_headers,
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "exercise_locked"

    unlock = plan_client.patch(
        f"/api/v1/plans/{plan_id}",
        json={
            "action": "lock",
            "expected_revision": 2,
            "plan_exercise_id": locked_exercise["id"],
            "locked": False,
        },
        headers=auth_headers,
    )
    assert unlock.status_code == 200
    unlocked_exercise = unlock.json()["days"][0]["exercises"][0]

    swapped = plan_client.patch(
        f"/api/v1/plans/{plan_id}",
        json={
            "action": "swap",
            "expected_revision": 3,
            "plan_exercise_id": unlocked_exercise["id"],
        },
        headers=auth_headers,
    )
    assert swapped.status_code == 200, swapped.text
    plan = swapped.json()
    replacement = plan["days"][0]["exercises"][0]
    assert replacement["exercise_id"] != unlocked_exercise["exercise_id"]
    assert replacement["locked"] is False
    assert plan["revision"] == 4


@pytest.mark.integration
def test_regenerate_day_preserves_locked_exercise(plan_client, auth_headers):
    created = create_plan(plan_client, auth_headers).json()
    plan_id = created["id"]
    first = created["days"][0]["exercises"][0]

    lock = plan_client.patch(
        f"/api/v1/plans/{plan_id}",
        json={
            "action": "lock",
            "expected_revision": 1,
            "plan_exercise_id": first["id"],
            "locked": True,
        },
        headers=auth_headers,
    )
    assert lock.status_code == 200

    regenerated = plan_client.patch(
        f"/api/v1/plans/{plan_id}",
        json={"action": "regenerate_day", "expected_revision": 2, "day": 1},
        headers=auth_headers,
    )
    assert regenerated.status_code == 200, regenerated.text
    plan = regenerated.json()
    assert plan["current_version"] == 3
    assert plan["revision"] == 3

    matching = [
        exercise
        for exercise in plan["days"][0]["exercises"]
        if exercise["exercise_id"] == first["exercise_id"]
    ]
    assert len(matching) == 1
    assert matching[0]["locked"] is True


@pytest.mark.integration
def test_revision_conflict_and_if_match(plan_client, auth_headers):
    created = create_plan(plan_client, auth_headers).json()
    plan_id = created["id"]
    first = created["days"][0]["exercises"][0]

    missing = plan_client.patch(
        f"/api/v1/plans/{plan_id}",
        json={"action": "lock", "plan_exercise_id": first["id"], "locked": True},
        headers=auth_headers,
    )
    assert missing.status_code == 428
    assert missing.json()["error"]["code"] == "precondition_required"

    changed = plan_client.patch(
        f"/api/v1/plans/{plan_id}",
        json={"action": "lock", "plan_exercise_id": first["id"], "locked": True},
        headers={**auth_headers, "If-Match": '"1"'},
    )
    assert changed.status_code == 200

    conflict = plan_client.patch(
        f"/api/v1/plans/{plan_id}",
        json={
            "action": "lock",
            "expected_revision": 1,
            "plan_exercise_id": first["id"],
            "locked": False,
        },
        headers=auth_headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "plan_revision_conflict"


@pytest.mark.integration
def test_share_is_read_only_and_revocable(plan_client, auth_headers, db_session):
    created = create_plan(
        plan_client,
        auth_headers,
        body=plan_body(recommendation=recommendation_body(injuries=["knee"])),
    ).json()
    plan_id = created["id"]

    share = plan_client.post(
        f"/api/v1/plans/{plan_id}/share",
        json={"expires_in_days": 7},
        headers=auth_headers,
    )
    assert share.status_code == 201, share.text
    share_body = share.json()
    token = share_body["token"]
    assert share_body["share_url"].endswith(token)

    stored = db_session.scalar(select(PlanShare))
    assert stored is not None
    assert stored.token_hash != token
    assert len(stored.token_hash) == 64

    public = plan_client.get(f"/api/v1/shared/{token}")
    assert public.status_code == 200, public.text
    public_body = public.json()
    assert public_body["title"] == "Test Plan"
    assert "input" not in public_body
    assert "owner_user_id" not in public_body
    assert "email" not in public_body
    assert "injuries" not in public_body
    assert public_body["days"]

    revoked = plan_client.delete(f"/api/v1/plans/{plan_id}/share", headers=auth_headers)
    assert revoked.status_code == 204
    assert plan_client.get(f"/api/v1/shared/{token}").status_code == 404


@pytest.mark.integration
def test_expired_share_is_rejected(plan_client, auth_headers, db_session):
    created = create_plan(plan_client, auth_headers).json()
    plan_id = created["id"]

    share = plan_client.post(
        f"/api/v1/plans/{plan_id}/share",
        json={"expires_in_days": 1},
        headers=auth_headers,
    )
    token = share.json()["token"]
    stored = db_session.scalar(select(PlanShare))
    assert stored is not None
    stored.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()

    assert plan_client.get(f"/api/v1/shared/{token}").status_code == 404


@pytest.mark.integration
def test_export_pdf_and_ics(plan_client, auth_headers, db_session):
    created = create_plan(plan_client, auth_headers).json()
    plan_id = created["id"]

    pdf = plan_client.get(f"/api/v1/plans/{plan_id}/export.pdf", headers=auth_headers)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.content.startswith(b"%PDF-")
    assert "attachment" in pdf.headers["content-disposition"]

    ics = plan_client.get(f"/api/v1/plans/{plan_id}/export.ics", headers=auth_headers)
    assert ics.status_code == 200
    assert "text/calendar" in ics.headers["content-type"]
    assert "BEGIN:VCALENDAR" in ics.text
    assert "BEGIN:VEVENT" in ics.text
    assert "SUMMARY:JYMZ Day 1" in ics.text

    actions = set(db_session.scalars(select(AuditLog.action)).all())
    assert "plan.exported" in actions
    assert count(db_session, AuditLog) >= 3


@pytest.mark.integration
def test_delete_is_soft_and_revokes_shares(plan_client, auth_headers, db_session):
    created = create_plan(plan_client, auth_headers).json()
    plan_id = created["id"]
    token = plan_client.post(
        f"/api/v1/plans/{plan_id}/share",
        json={"expires_in_days": 7},
        headers=auth_headers,
    ).json()["token"]

    deleted = plan_client.delete(f"/api/v1/plans/{plan_id}", headers=auth_headers)
    assert deleted.status_code == 204
    assert plan_client.get(f"/api/v1/plans/{plan_id}", headers=auth_headers).status_code == 404
    assert plan_client.get(f"/api/v1/shared/{token}").status_code == 404
    assert plan_client.get("/api/v1/plans", headers=auth_headers).json()["items"] == []

    plan = db_session.scalar(select(Plan).where(Plan.id == uuid.UUID(plan_id)))
    assert plan is not None
    assert plan.deleted_at is not None
    share = db_session.scalar(
        select(PlanShare).where(PlanShare.plan_id == uuid.UUID(plan_id))
    )
    assert share is not None
    assert share.revoked_at is not None

    recreated = create_plan(plan_client, auth_headers, key="plan-key-1")
    assert recreated.status_code == 201
    assert recreated.json()["id"] != plan_id


@pytest.mark.integration
def test_plan_list_pagination(plan_client, auth_headers):
    for index in range(3):
        response = create_plan(
            plan_client,
            auth_headers,
            key=f"page-key-{index}",
            body=plan_body(title=f"Plan {index}"),
        )
        assert response.status_code == 201

    first_page = plan_client.get("/api/v1/plans?limit=2", headers=auth_headers)
    assert first_page.status_code == 200
    body = first_page.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"]

    second_page = plan_client.get(
        f"/api/v1/plans?limit=2&cursor={body['next_cursor']}",
        headers=auth_headers,
    )
    assert second_page.status_code == 200
    assert len(second_page.json()["items"]) == 1
    assert second_page.json()["next_cursor"] is None

    invalid = plan_client.get("/api/v1/plans?cursor=not-a-uuid", headers=auth_headers)
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_cursor"


@pytest.mark.integration
def test_plan_openapi(plan_client):
    document = plan_client.get("/openapi.json").json()
    paths = document["paths"]
    assert "/api/v1/plans" in paths
    assert "/api/v1/plans/{plan_id}" in paths
    assert "/api/v1/plans/{plan_id}/versions" in paths
    assert "/api/v1/plans/{plan_id}/share" in paths
    assert "/api/v1/plans/{plan_id}/export.pdf" in paths
    assert "/api/v1/plans/{plan_id}/export.ics" in paths
    assert "/api/v1/shared/{token}" in paths
    assert "OIDCBearer" in document["components"]["securitySchemes"]
