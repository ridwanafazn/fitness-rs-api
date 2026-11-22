"""Integration tests for P1.1 progress, history, and insights."""

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
from app.db.models import WorkoutSession
from app.main import create_app

SECRET = "test-secret-" + ("x" * 40)
ISSUER = "https://issuer.test"
AUDIENCE = "fitness-api-test"


@pytest.fixture()
def progress_settings(dataset_path: Path, tmp_path: Path) -> Settings:
    database_path = (tmp_path / "progress.db").as_posix()
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
        progress_enabled=True,
        auth_dev_mode=True,
        auth_dev_secret=SECRET,
        auth_issuer=ISSUER,
        auth_audience=AUDIENCE,
    )


@pytest.fixture()
def progress_app(progress_settings: Settings):
    return create_app(progress_settings)


@pytest.fixture()
def progress_client(progress_app):
    with TestClient(progress_app) as client:
        yield client


@pytest.fixture()
def db_session(progress_client, progress_app) -> Session:
    session = progress_app.state.session_factory()
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


def create_plan(client, headers, *, key: str = "progress-plan-1"):
    return client.post(
        "/api/v1/plans",
        json={
            "recommendation": recommendation_body(),
            "title": "Progress Plan",
        },
        headers={**headers, "Idempotency-Key": key},
    )


def start_workout(client, headers, plan_id: str, *, day: int = 1, key: str | None = None):
    payload = {"plan_id": plan_id, "day": day, "timezone": "Asia/Jakarta"}
    if key:
        payload["client_session_id"] = key
    return client.post("/api/v1/workouts/start", json=payload, headers=headers)


def add_set(client, headers, workout_id: str, exercise_id: str, *, number: int, reps: int, weight: float):
    return client.post(
        f"/api/v1/workouts/{workout_id}/sets",
        json={
            "workout_exercise_id": exercise_id,
            "set_number": number,
            "reps": reps,
            "weight_kg": weight,
            "client_set_id": str(uuid.uuid4()),
        },
        headers=headers,
    )


def complete(client, headers, workout_id: str):
    return client.post(
        f"/api/v1/workouts/{workout_id}/complete",
        json={},
        headers=headers,
    )


def today_in_jakarta():
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Jakarta")).date()


@pytest.mark.integration
def test_progress_is_feature_flagged(client):
    assert client.get("/api/v1/me/progress").status_code == 404
    assert client.get("/api/v1/me/insights").status_code == 404


@pytest.mark.integration
def test_progress_after_completed_workout(progress_client, auth_headers):
    plan = create_plan(progress_client, auth_headers).json()
    workout = start_workout(
        progress_client,
        auth_headers,
        plan["id"],
        key=str(uuid.uuid4()),
    ).json()
    exercise = workout["exercises"][0]
    add_set(
        progress_client,
        auth_headers,
        workout["id"],
        exercise["id"],
        number=1,
        reps=10,
        weight=20,
    )
    add_set(
        progress_client,
        auth_headers,
        workout["id"],
        exercise["id"],
        number=2,
        reps=8,
        weight=25,
    )
    assert complete(progress_client, auth_headers, workout["id"]).status_code == 200

    today = today_in_jakarta()
    response = progress_client.get(
        f"/api/v1/me/progress?from_date={today - timedelta(days=7)}&to_date={today}&timezone=Asia/Jakarta",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timezone"] == "Asia/Jakarta"
    assert body["totals"]["workouts_completed"] == 1
    assert body["totals"]["total_sets"] == 2
    assert body["totals"]["total_reps"] == 18
    assert body["totals"]["total_volume_kg"] == 400
    assert body["days"]
    assert body["days"][0]["date"] == str(today)
    assert sum(body["sets_by_body_part"].values()) == 2
    assert body["streak_days"] >= 1


@pytest.mark.integration
def test_progress_excludes_deleted_sets(progress_client, auth_headers):
    plan = create_plan(progress_client, auth_headers, key="deleted-set-plan").json()
    workout = start_workout(
        progress_client,
        auth_headers,
        plan["id"],
        key=str(uuid.uuid4()),
    ).json()
    exercise = workout["exercises"][0]
    added = add_set(
        progress_client,
        auth_headers,
        workout["id"],
        exercise["id"],
        number=1,
        reps=10,
        weight=20,
    ).json()
    assert progress_client.delete(
        f"/api/v1/sets/{added['id']}",
        headers=auth_headers,
    ).status_code == 204
    assert complete(progress_client, auth_headers, workout["id"]).status_code == 200

    response = progress_client.get("/api/v1/me/progress", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["totals"]["total_sets"] == 0
    assert response.json()["totals"]["total_volume_kg"] == 0


@pytest.mark.integration
def test_progress_streak_uses_local_dates(progress_client, auth_headers, db_session):
    plan = create_plan(progress_client, auth_headers, key="streak-plan").json()
    workout = start_workout(
        progress_client,
        auth_headers,
        plan["id"],
        key=str(uuid.uuid4()),
    ).json()
    assert complete(progress_client, auth_headers, workout["id"]).status_code == 200

    session = db_session.scalar(
        select(WorkoutSession).where(WorkoutSession.id == uuid.UUID(workout["id"]))
    )
    assert session is not None
    session.started_at = datetime.now(UTC) - timedelta(days=1)
    session.completed_at = datetime.now(UTC) - timedelta(days=1)
    db_session.commit()

    response = progress_client.get("/api/v1/me/progress", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["streak_days"] >= 1


@pytest.mark.integration
def test_history_pagination_and_owner_isolation(progress_client, token_factory):
    alice = {"Authorization": f"Bearer {token_factory('alice')}"}
    bob = {"Authorization": f"Bearer {token_factory('bob')}"}
    alice_plan = create_plan(progress_client, alice, key="alice-progress").json()

    workout_ids = []
    for day in (1, 2):
        workout = start_workout(
            progress_client,
            alice,
            alice_plan["id"],
            day=day,
            key=str(uuid.uuid4()),
        ).json()
        complete(progress_client, alice, workout["id"])
        workout_ids.append(workout["id"])

    bob_plan = create_plan(progress_client, bob, key="bob-progress").json()
    bob_workout = start_workout(
        progress_client,
        bob,
        bob_plan["id"],
        key=str(uuid.uuid4()),
    ).json()
    complete(progress_client, bob, bob_workout["id"])

    first_page = progress_client.get("/api/v1/me/history?limit=1", headers=alice)
    assert first_page.status_code == 200
    assert len(first_page.json()["items"]) == 1
    assert first_page.json()["next_cursor"]
    second_page = progress_client.get(
        f"/api/v1/me/history?limit=1&cursor={first_page.json()['next_cursor']}",
        headers=alice,
    )
    assert second_page.status_code == 200
    assert len(second_page.json()["items"]) == 1
    assert {
        first_page.json()["items"][0]["id"],
        second_page.json()["items"][0]["id"],
    } == set(workout_ids)

    bob_history = progress_client.get("/api/v1/me/history", headers=bob)
    assert len(bob_history.json()["items"]) == 1


@pytest.mark.integration
def test_insights_personal_records_and_weekly_review(progress_client, auth_headers):
    plan = create_plan(progress_client, auth_headers, key="insights-plan").json()
    workout = start_workout(
        progress_client,
        auth_headers,
        plan["id"],
        key=str(uuid.uuid4()),
    ).json()
    exercise = workout["exercises"][0]
    add_set(
        progress_client,
        auth_headers,
        workout["id"],
        exercise["id"],
        number=1,
        reps=10,
        weight=20,
    )
    add_set(
        progress_client,
        auth_headers,
        workout["id"],
        exercise["id"],
        number=2,
        reps=8,
        weight=25,
    )
    complete(progress_client, auth_headers, workout["id"])

    response = progress_client.get("/api/v1/me/insights", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["streak_days"] >= 1
    assert body["workouts_last_28_days"] == 1
    assert body["current_week"] is not None
    assert body["current_week"]["workouts_completed"] == 1
    assert body["body_part_balance"]
    assert body["personal_records"]
    records = {
        item["record_type"]: item for item in body["personal_records"]
    }
    assert records["max_weight"]["value"] == 25
    assert records["max_reps"]["value"] == 10
    assert records["max_volume"]["value"] == 200
    assert "28 hari terakhir" in body["summary"]


@pytest.mark.integration
def test_progress_validation(progress_client, auth_headers):
    invalid_range = progress_client.get(
        "/api/v1/me/progress?from_date=2026-11-30&to_date=2026-11-01",
        headers=auth_headers,
    )
    assert invalid_range.status_code == 422
    assert invalid_range.json()["error"]["code"] == "progress_invalid"

    invalid_timezone = progress_client.get(
        "/api/v1/me/insights?timezone=Mars/Olympus",
        headers=auth_headers,
    )
    assert invalid_timezone.status_code == 422
    assert invalid_timezone.json()["error"]["code"] == "progress_invalid"


@pytest.mark.integration
def test_progress_openapi(progress_client):
    document = progress_client.get("/openapi.json").json()
    paths = document["paths"]
    assert "/api/v1/me/progress" in paths
    assert "/api/v1/me/history" in paths
    assert "/api/v1/me/insights" in paths
