"""Integration tests for P0.3 workout execution and offline sync."""

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
    ClientMutation,
    SetLog,
    WorkoutSession,
)
from app.domain.constants import Focus
from app.domain.focus import is_exercise_focus
from app.main import create_app

SECRET = "test-secret-" + ("x" * 40)
ISSUER = "https://issuer.test"
AUDIENCE = "fitness-api-test"


@pytest.fixture()
def workout_settings(dataset_path: Path, tmp_path: Path) -> Settings:
    database_path = (tmp_path / "workouts.db").as_posix()
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
        auth_dev_mode=True,
        auth_dev_secret=SECRET,
        auth_issuer=ISSUER,
        auth_audience=AUDIENCE,
    )


@pytest.fixture()
def workout_app(workout_settings: Settings):
    return create_app(workout_settings)


@pytest.fixture()
def workout_client(workout_app):
    with TestClient(workout_app) as client:
        yield client


@pytest.fixture()
def db_session(workout_client, workout_app) -> Session:
    session = workout_app.state.session_factory()
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


def create_plan(client, headers, *, key: str = "workout-plan-1", injuries: list[str] | None = None):
    payload = {
        "recommendation": recommendation_body(injuries=injuries or []),
        "title": "Workout Plan",
    }
    return client.post(
        "/api/v1/plans",
        json=payload,
        headers={**headers, "Idempotency-Key": key},
    )


def start_workout(
    client,
    headers,
    plan_id: str,
    *,
    day: int = 1,
    client_session_id: str | None = None,
):
    payload = {
        "plan_id": plan_id,
        "day": day,
        "timezone": "Asia/Jakarta",
    }
    if client_session_id:
        payload["client_session_id"] = client_session_id
    return client.post("/api/v1/workouts/start", json=payload, headers=headers)


def count(session: Session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


@pytest.mark.integration
def test_workouts_are_feature_flagged(client):
    response = client.get("/api/v1/workouts")
    assert response.status_code == 404


@pytest.mark.integration
def test_start_workout_and_client_session_idempotency(workout_client, auth_headers, db_session):
    plan = create_plan(workout_client, auth_headers).json()
    client_session_id = str(uuid.uuid4())

    first = start_workout(
        workout_client,
        auth_headers,
        plan["id"],
        client_session_id=client_session_id,
    )
    assert first.status_code == 201, first.text
    workout = first.json()
    assert workout["status"] == "in_progress"
    assert workout["timezone"] == "Asia/Jakarta"
    assert workout["day_number"] == 1
    assert workout["exercise_count"] == len(workout["exercises"])
    assert workout["exercises"]
    assert workout["exercises"][0]["exercise_image"]

    second = start_workout(
        workout_client,
        auth_headers,
        plan["id"],
        client_session_id=client_session_id,
    )
    assert second.status_code == 201
    assert second.json()["id"] == workout["id"]
    assert count(db_session, WorkoutSession) == 1

    day_two = start_workout(workout_client, auth_headers, plan["id"], day=2)
    assert day_two.status_code == 201
    assert day_two.json()["day_number"] == 2

    invalid_day = start_workout(workout_client, auth_headers, plan["id"], day=5)
    assert invalid_day.status_code == 422
    assert invalid_day.json()["error"]["code"] == "workout_invalid"


@pytest.mark.integration
def test_set_logging_totals_and_idempotency(workout_client, auth_headers, db_session):
    plan = create_plan(workout_client, auth_headers).json()
    workout = start_workout(workout_client, auth_headers, plan["id"]).json()
    workout_id = workout["id"]
    exercise_id = workout["exercises"][0]["id"]
    client_set_id = str(uuid.uuid4())

    payload = {
        "workout_exercise_id": exercise_id,
        "set_number": 1,
        "reps": 10,
        "weight_kg": 20,
        "rpe": 8,
        "client_set_id": client_set_id,
    }
    first = workout_client.post(
        f"/api/v1/workouts/{workout_id}/sets",
        json=payload,
        headers=auth_headers,
    )
    assert first.status_code == 201, first.text
    set_id = first.json()["id"]

    replay = workout_client.post(
        f"/api/v1/workouts/{workout_id}/sets",
        json=payload,
        headers=auth_headers,
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == set_id
    assert count(db_session, SetLog) == 1

    conflict = workout_client.post(
        f"/api/v1/workouts/{workout_id}/sets",
        json={
            **payload,
            "client_set_id": str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "set_conflict"

    detail = workout_client.get(f"/api/v1/workouts/{workout_id}", headers=auth_headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["total_sets"] == 1
    assert body["total_reps"] == 10
    assert body["total_volume_kg"] == 200
    assert len(body["exercises"][0]["sets"]) == 1

    updated = workout_client.patch(
        f"/api/v1/sets/{set_id}",
        json={"reps": 12, "weight_kg": 22.5},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["reps"] == 12

    detail = workout_client.get(f"/api/v1/workouts/{workout_id}", headers=auth_headers).json()
    assert detail["total_reps"] == 12
    assert detail["total_volume_kg"] == 270

    deleted = workout_client.delete(f"/api/v1/sets/{set_id}", headers=auth_headers)
    assert deleted.status_code == 204
    detail = workout_client.get(f"/api/v1/workouts/{workout_id}", headers=auth_headers).json()
    assert detail["total_sets"] == 0
    assert detail["exercises"][0]["sets"] == []


@pytest.mark.integration
def test_complete_is_idempotent_and_blocks_edits(workout_client, auth_headers):
    plan = create_plan(workout_client, auth_headers).json()
    workout = start_workout(workout_client, auth_headers, plan["id"]).json()
    workout_id = workout["id"]
    exercise_id = workout["exercises"][0]["id"]

    added = workout_client.post(
        f"/api/v1/workouts/{workout_id}/sets",
        json={
            "workout_exercise_id": exercise_id,
            "set_number": 1,
            "reps": 8,
            "weight_kg": 30,
            "client_set_id": str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    assert added.status_code == 201

    completed = workout_client.post(
        f"/api/v1/workouts/{workout_id}/complete",
        json={"notes": "done"},
        headers=auth_headers,
    )
    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert body["status"] == "completed"
    assert body["completed_at"] is not None
    assert body["duration_seconds"] is not None
    assert body["total_sets"] == 1

    replay = workout_client.post(
        f"/api/v1/workouts/{workout_id}/complete",
        json={"notes": "done again"},
        headers=auth_headers,
    )
    assert replay.status_code == 200
    assert replay.json()["completed_at"] == body["completed_at"]

    blocked_set = workout_client.post(
        f"/api/v1/workouts/{workout_id}/sets",
        json={
            "workout_exercise_id": exercise_id,
            "set_number": 2,
            "reps": 8,
            "client_set_id": str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    assert blocked_set.status_code == 409
    assert blocked_set.json()["error"]["code"] == "workout_completed"

    set_id = added.json()["id"]
    blocked_delete = workout_client.delete(f"/api/v1/sets/{set_id}", headers=auth_headers)
    assert blocked_delete.status_code == 409


@pytest.mark.integration
def test_substitute_exercise_and_reject_unsafe(workout_client, workout_app, auth_headers):
    plan = create_plan(workout_client, auth_headers).json()
    workout = start_workout(workout_client, auth_headers, plan["id"]).json()
    workout_id = workout["id"]
    first = workout["exercises"][0]
    used_ids = {exercise["exercise_id"] for exercise in workout["exercises"]}
    focus = Focus(workout["focus"])
    dataset = workout_app.state.dataset
    replacement = next(
        exercise
        for exercise in dataset.exercises
        if exercise.exercise_id not in used_ids
        and is_exercise_focus(exercise.body_part, focus)
    )

    response = workout_client.post(
        f"/api/v1/workouts/{workout_id}/exercises/{first['id']}/substitute",
        json={"replacement_exercise_id": replacement.exercise_id},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    substituted = next(
        exercise for exercise in body["exercises"] if exercise["id"] == first["id"]
    )
    assert substituted["exercise_id"] == replacement.exercise_id
    assert substituted["substituted_from_exercise_id"] == first["exercise_id"]

    unsafe_plan = create_plan(
        workout_client,
        auth_headers,
        key="unsafe-workout-plan",
        injuries=["chest"],
    ).json()
    unsafe_workout = start_workout(
        workout_client,
        auth_headers,
        unsafe_plan["id"],
    ).json()
    chest_exercise = next(
        exercise for exercise in dataset.exercises if exercise.body_part.value == "chest"
    )
    blocked = workout_client.post(
        f"/api/v1/workouts/{unsafe_workout['id']}/exercises/{unsafe_workout['exercises'][0]['id']}/substitute",
        json={"replacement_exercise_id": chest_exercise.exercise_id},
        headers=auth_headers,
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "workout_invalid"


@pytest.mark.integration
def test_workout_history_pagination_and_owner_isolation(workout_client, token_factory):
    alice = {"Authorization": f"Bearer {token_factory('alice')}"}
    bob = {"Authorization": f"Bearer {token_factory('bob')}"}
    alice_plan = create_plan(workout_client, alice, key="alice-workout-plan").json()

    first = start_workout(
        workout_client,
        alice,
        alice_plan["id"],
        day=1,
        client_session_id=str(uuid.uuid4()),
    ).json()
    second = start_workout(
        workout_client,
        alice,
        alice_plan["id"],
        day=2,
        client_session_id=str(uuid.uuid4()),
    ).json()

    bob_plan = create_plan(workout_client, bob, key="bob-workout-plan").json()
    start_workout(
        workout_client,
        bob,
        bob_plan["id"],
        day=1,
        client_session_id=str(uuid.uuid4()),
    )

    alice_list = workout_client.get("/api/v1/workouts", headers=alice)
    bob_list = workout_client.get("/api/v1/workouts", headers=bob)
    assert alice_list.status_code == 200
    assert len(alice_list.json()["items"]) == 2
    assert len(bob_list.json()["items"]) == 1

    first_page = workout_client.get("/api/v1/workouts?limit=1", headers=alice).json()
    assert len(first_page["items"]) == 1
    assert first_page["next_cursor"]
    second_page = workout_client.get(
        f"/api/v1/workouts?limit=1&cursor={first_page['next_cursor']}",
        headers=alice,
    ).json()
    assert len(second_page["items"]) == 1
    assert {first_page["items"][0]["id"], second_page["items"][0]["id"]} == {
        first["id"],
        second["id"],
    }

    assert workout_client.get(f"/api/v1/workouts/{first['id']}", headers=bob).status_code == 404


@pytest.mark.integration
def test_sync_batch_partial_failure_and_idempotency(workout_client, auth_headers, db_session):
    plan = create_plan(workout_client, auth_headers).json()
    workout = start_workout(workout_client, auth_headers, plan["id"]).json()
    workout_id = workout["id"]
    exercise_id = workout["exercises"][0]["id"]
    client_set_id = str(uuid.uuid4())

    mutations = {
        "mutations": [
            {
                "client_mutation_id": "m-create",
                "type": "set.create",
                "payload": {
                    "workout_id": workout_id,
                    "workout_exercise_id": exercise_id,
                    "set_number": 1,
                    "reps": 10,
                    "weight_kg": 20,
                    "client_set_id": client_set_id,
                },
            },
            {
                "client_mutation_id": "m-bad-workout",
                "type": "set.create",
                "payload": {
                    "workout_id": str(uuid.uuid4()),
                    "workout_exercise_id": exercise_id,
                    "set_number": 2,
                    "reps": 10,
                    "client_set_id": str(uuid.uuid4()),
                },
            },
        ]
    }

    first = workout_client.post("/api/v1/sync/batch", json=mutations, headers=auth_headers)
    assert first.status_code == 200, first.text
    results = first.json()["results"]
    assert [item["status"] for item in results] == ["applied", "error"]
    assert results[1]["error"]["code"] == "workout_not_found"
    assert count(db_session, SetLog) == 1
    assert count(db_session, ClientMutation) == 1

    replay = workout_client.post("/api/v1/sync/batch", json=mutations, headers=auth_headers)
    assert replay.status_code == 200
    statuses = [item["status"] for item in replay.json()["results"]]
    assert statuses == ["duplicate", "error"]
    assert count(db_session, SetLog) == 1
    assert count(db_session, ClientMutation) == 1


@pytest.mark.integration
def test_sync_batch_replay_three_times(workout_client, auth_headers, db_session):
    plan = create_plan(workout_client, auth_headers).json()
    workout = start_workout(workout_client, auth_headers, plan["id"]).json()
    mutation = {
        "mutations": [
            {
                "client_mutation_id": "m-replay",
                "type": "set.create",
                "payload": {
                    "workout_id": workout["id"],
                    "workout_exercise_id": workout["exercises"][0]["id"],
                    "set_number": 1,
                    "reps": 8,
                    "weight_kg": 25,
                    "client_set_id": str(uuid.uuid4()),
                },
            }
        ]
    }

    for index in range(3):
        response = workout_client.post("/api/v1/sync/batch", json=mutation, headers=auth_headers)
        assert response.status_code == 200
        expected = "applied" if index == 0 else "duplicate"
        assert response.json()["results"][0]["status"] == expected

    assert count(db_session, SetLog) == 1
    assert count(db_session, ClientMutation) == 1


@pytest.mark.integration
def test_workout_audit_has_no_notes_or_pii(workout_client, auth_headers, db_session):
    plan = create_plan(workout_client, auth_headers).json()
    workout = start_workout(workout_client, auth_headers, plan["id"]).json()
    workout_client.post(
        f"/api/v1/workouts/{workout['id']}/sets",
        json={
            "workout_exercise_id": workout["exercises"][0]["id"],
            "set_number": 1,
            "reps": 10,
            "weight_kg": 20,
            "notes": "private knee note",
            "client_set_id": str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    workout_client.post(
        f"/api/v1/workouts/{workout['id']}/complete",
        json={"notes": "private session note"},
        headers=auth_headers,
    )

    serialized = " ".join(
        str(row.metadata_json)
        for row in db_session.scalars(select(AuditLog)).all()
    )
    assert "private knee note" not in serialized
    assert "private session note" not in serialized
    assert "user-1@example.com" not in serialized


@pytest.mark.integration
def test_sync_batch_update_substitute_delete_and_complete(
    workout_client,
    workout_app,
    auth_headers,
):
    plan = create_plan(workout_client, auth_headers).json()
    workout = start_workout(workout_client, auth_headers, plan["id"]).json()
    workout_id = workout["id"]
    first = workout["exercises"][0]
    set_response = workout_client.post(
        f"/api/v1/workouts/{workout_id}/sets",
        json={
            "workout_exercise_id": first["id"],
            "set_number": 1,
            "reps": 10,
            "weight_kg": 20,
            "client_set_id": str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    set_id = set_response.json()["id"]

    used_ids = {exercise["exercise_id"] for exercise in workout["exercises"]}
    dataset = workout_app.state.dataset
    replacement = next(
        exercise
        for exercise in dataset.exercises
        if exercise.exercise_id not in used_ids
        and is_exercise_focus(exercise.body_part, Focus(workout["focus"]))
    )

    mutations = {
        "mutations": [
            {
                "client_mutation_id": "m-update",
                "type": "set.update",
                "payload": {"set_id": set_id, "reps": 12, "rpe": 9},
            },
            {
                "client_mutation_id": "m-substitute",
                "type": "exercise.substitute",
                "payload": {
                    "workout_id": workout_id,
                    "workout_exercise_id": first["id"],
                    "replacement_exercise_id": replacement.exercise_id,
                },
            },
            {
                "client_mutation_id": "m-delete",
                "type": "set.delete",
                "payload": {"set_id": set_id},
            },
            {
                "client_mutation_id": "m-complete",
                "type": "workout.complete",
                "payload": {"workout_id": workout_id, "notes": "offline complete"},
            },
        ]
    }

    response = workout_client.post("/api/v1/sync/batch", json=mutations, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert [item["status"] for item in response.json()["results"]] == ["applied"] * 4

    detail = workout_client.get(f"/api/v1/workouts/{workout_id}", headers=auth_headers).json()
    assert detail["status"] == "completed"
    assert detail["total_sets"] == 0
    substituted = next(
        exercise for exercise in detail["exercises"] if exercise["id"] == first["id"]
    )
    assert substituted["exercise_id"] == replacement.exercise_id
    assert substituted["sets"] == []


@pytest.mark.integration
def test_owner_cannot_add_set_to_another_users_workout(workout_client, token_factory):
    alice = {"Authorization": f"Bearer {token_factory('alice')}"}
    bob = {"Authorization": f"Bearer {token_factory('bob')}"}
    plan = create_plan(workout_client, alice, key="alice-set-plan").json()
    workout = start_workout(workout_client, alice, plan["id"]).json()

    response = workout_client.post(
        f"/api/v1/workouts/{workout['id']}/sets",
        json={
            "workout_exercise_id": workout["exercises"][0]["id"],
            "set_number": 1,
            "reps": 10,
            "client_set_id": str(uuid.uuid4()),
        },
        headers=bob,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "workout_not_found"


@pytest.mark.integration
def test_invalid_workout_timezone_is_rejected(workout_client, auth_headers):
    plan = create_plan(workout_client, auth_headers).json()
    response = workout_client.post(
        "/api/v1/workouts/start",
        json={"plan_id": plan["id"], "day": 1, "timezone": "Mars/Olympus"},
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_empty_set_update_is_rejected(workout_client, auth_headers):
    plan = create_plan(workout_client, auth_headers).json()
    workout = start_workout(workout_client, auth_headers, plan["id"]).json()
    added = workout_client.post(
        f"/api/v1/workouts/{workout['id']}/sets",
        json={
            "workout_exercise_id": workout["exercises"][0]["id"],
            "set_number": 1,
            "reps": 10,
            "client_set_id": str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    response = workout_client.patch(
        f"/api/v1/sets/{added.json()['id']}",
        json={},
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_workout_openapi(workout_client):
    document = workout_client.get("/openapi.json").json()
    paths = document["paths"]
    assert "/api/v1/workouts/start" in paths
    assert "/api/v1/workouts" in paths
    assert "/api/v1/workouts/{workout_id}" in paths
    assert "/api/v1/workouts/{workout_id}/sets" in paths
    assert "/api/v1/sets/{set_id}" in paths
    assert "/api/v1/sync/batch" in paths
