"""Integration tests for P1.2 trainer workspace and access control."""

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
from app.db.models import AuditLog, TrainerInvitation, User, UserRole
from app.main import create_app

SECRET = "test-secret-" + ("x" * 40)
ISSUER = "https://issuer.test"
AUDIENCE = "fitness-api-test"


@pytest.fixture()
def trainer_settings(dataset_path: Path, tmp_path: Path) -> Settings:
    database_path = (tmp_path / "trainer.db").as_posix()
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
        auth_dev_mode=True,
        auth_dev_secret=SECRET,
        auth_issuer=ISSUER,
        auth_audience=AUDIENCE,
    )


@pytest.fixture()
def trainer_app(trainer_settings: Settings):
    return create_app(trainer_settings)


@pytest.fixture()
def trainer_client(trainer_app):
    with TestClient(trainer_app) as client:
        yield client


@pytest.fixture()
def db_session(trainer_client, trainer_app) -> Session:
    session = trainer_app.state.session_factory()
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


def make_trainer(client, db_session: Session, token_factory, sub: str = "trainer-1") -> dict:
    email = f"{sub}@example.com"
    headers = {"Authorization": f"Bearer {token_factory(sub, email)}"}
    client.get("/api/v1/me", headers=headers)
    user = db_session.scalar(select(User).where(User.auth_subject == sub))
    assert user is not None
    db_session.add(UserRole(user_id=user.id, role="trainer"))
    db_session.commit()
    return headers


def make_client(client, token_factory, sub: str = "client-1") -> dict:
    headers = {"Authorization": f"Bearer {token_factory(sub, f'{sub}@example.com')}"}
    assert client.get("/api/v1/me", headers=headers).status_code == 200
    return headers


def create_invitation(client, trainer_headers, email: str, scopes: list[str]):
    return client.post(
        "/api/v1/trainer/invitations",
        json={
            "client_email": email,
            "scopes": scopes,
            "message": "let's work together",
        },
        headers=trainer_headers,
    )


def accept_invitation(client, client_headers, token: str, scopes: list[str]):
    return client.post(
        f"/api/v1/trainer/invitations/{token}/accept",
        json={"scopes": scopes},
        headers=client_headers,
    )


def create_plan(client, headers, key: str = "trainer-plan-1"):
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
            "title": "Client Plan",
        },
        headers={**headers, "Idempotency-Key": key},
    )


def start_and_complete(client, headers, plan_id: str):
    workout = client.post(
        "/api/v1/workouts/start",
        json={
            "plan_id": plan_id,
            "day": 1,
            "timezone": "Asia/Jakarta",
            "client_session_id": str(uuid.uuid4()),
        },
        headers=headers,
    ).json()
    exercise = workout["exercises"][0]
    client.post(
        f"/api/v1/workouts/{workout['id']}/sets",
        json={
            "workout_exercise_id": exercise["id"],
            "set_number": 1,
            "reps": 10,
            "weight_kg": 20,
            "client_set_id": str(uuid.uuid4()),
        },
        headers=headers,
    )
    client.post(
        f"/api/v1/workouts/{workout['id']}/complete",
        json={},
        headers=headers,
    )
    return workout


@pytest.mark.integration
def test_trainer_is_feature_flagged(client):
    assert client.get("/api/v1/trainer/profile").status_code == 404


@pytest.mark.integration
def test_trainer_profile_requires_role(trainer_client, token_factory, db_session):
    headers = {"Authorization": f"Bearer {token_factory('plain-user')}"}
    assert trainer_client.get("/api/v1/me", headers=headers).status_code == 200
    denied = trainer_client.put(
        "/api/v1/trainer/profile",
        json={"display_name": "Coach"},
        headers=headers,
    )
    assert denied.status_code == 403

    trainer_headers = make_trainer(trainer_client, db_session, token_factory)
    created = trainer_client.put(
        "/api/v1/trainer/profile",
        json={
            "display_name": "Coach One",
            "bio": "strength coach",
            "specialties": ["powerlifting", "hypertrophy"],
            "years_experience": 5,
        },
        headers=trainer_headers,
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["display_name"] == "Coach One"
    assert body["specialties"] == ["powerlifting", "hypertrophy"]

    updated = trainer_client.put(
        "/api/v1/trainer/profile",
        json={"display_name": "Coach One Updated", "specialties": ["strength"]},
        headers=trainer_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Coach One Updated"
    assert trainer_client.get(
        "/api/v1/trainer/profile", headers=trainer_headers
    ).status_code == 200


@pytest.mark.integration
def test_invitation_create_self_and_duplicate(
    trainer_client,
    token_factory,
    db_session,
):
    trainer_headers = make_trainer(trainer_client, db_session, token_factory)
    self_invite = create_invitation(
        trainer_client,
        trainer_headers,
        "trainer-1@example.com",
        ["plans"],
    )
    assert self_invite.status_code == 409

    first = create_invitation(
        trainer_client,
        trainer_headers,
        "client@example.com",
        ["plans", "workouts"],
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["token"]
    assert body["token"] in body["invite_url"]
    assert body["invite_url"].endswith("/accept")
    assert body["requested_scopes"] == ["plans", "workouts"]

    duplicate = create_invitation(
        trainer_client,
        trainer_headers,
        "client@example.com",
        ["plans"],
    )
    assert duplicate.status_code == 409
    invitations = trainer_client.get(
        "/api/v1/trainer/invitations", headers=trainer_headers
    )
    assert invitations.status_code == 200
    assert len(invitations.json()["items"]) == 1


@pytest.mark.integration
def test_invitation_accept_and_client_trainer_view(
    trainer_client,
    token_factory,
    db_session,
):
    trainer_headers = make_trainer(trainer_client, db_session, token_factory)
    client_headers = make_client(trainer_client, token_factory)
    invitation = create_invitation(
        trainer_client,
        trainer_headers,
        "client-1@example.com",
        ["plans", "workouts", "feedback", "progress"],
    ).json()

    accepted = accept_invitation(
        trainer_client,
        client_headers,
        invitation["token"],
        ["plans", "workouts", "feedback", "progress"],
    )
    assert accepted.status_code == 200, accepted.text
    link = accepted.json()
    assert set(link["scopes"]) == {"plans", "workouts", "feedback", "progress"}

    clients = trainer_client.get("/api/v1/trainer/clients", headers=trainer_headers)
    assert clients.status_code == 200
    assert clients.json()["items"][0]["client_user_id"] == link["client_user_id"]

    trainers = trainer_client.get("/api/v1/me/trainers", headers=client_headers)
    assert trainers.status_code == 200
    assert trainers.json()["items"][0]["trainer_user_id"] == link["trainer_user_id"]
    assert "plans" in trainers.json()["items"][0]["scopes"]

    actions = set(db_session.scalars(select(AuditLog.action)).all())
    assert "trainer.invitation_created" in actions
    assert "trainer.invitation_accepted" in actions


@pytest.mark.integration
def test_invitation_wrong_user_and_expired(
    trainer_client,
    token_factory,
    db_session,
):
    trainer_headers = make_trainer(trainer_client, db_session, token_factory)
    make_client(trainer_client, token_factory, sub="client-wrong")
    invitation = create_invitation(
        trainer_client,
        trainer_headers,
        "client-1@example.com",
        ["plans"],
    ).json()

    wrong_headers = {
        "Authorization": f"Bearer {token_factory('wrong-user', 'wrong@example.com')}"
    }
    trainer_client.get("/api/v1/me", headers=wrong_headers)
    wrong = accept_invitation(
        trainer_client, wrong_headers, invitation["token"], ["plans"]
    )
    assert wrong.status_code == 403

    stored = db_session.scalar(
        select(TrainerInvitation).where(
            TrainerInvitation.id == uuid.UUID(invitation["id"])
        )
    )
    assert stored is not None
    stored.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()
    expired = accept_invitation(
        trainer_client,
        make_client(trainer_client, token_factory),
        invitation["token"],
        ["plans"],
    )
    assert expired.status_code == 404
    assert expired.json()["error"]["code"] == "trainer_invitation_not_found"


@pytest.mark.integration
def test_invitation_decline(trainer_client, token_factory, db_session):
    trainer_headers = make_trainer(trainer_client, db_session, token_factory)
    client_headers = make_client(trainer_client, token_factory)
    invitation = create_invitation(
        trainer_client,
        trainer_headers,
        "client-1@example.com",
        ["plans"],
    ).json()
    declined = trainer_client.post(
        f"/api/v1/trainer/invitations/{invitation['token']}/decline",
        headers=client_headers,
    )
    assert declined.status_code == 204
    assert trainer_client.get(
        "/api/v1/trainer/clients", headers=trainer_headers
    ).json()["items"] == []


@pytest.mark.integration
def test_scope_enforcement(trainer_client, token_factory, db_session):
    trainer_headers = make_trainer(trainer_client, db_session, token_factory)
    client_headers = make_client(trainer_client, token_factory)
    invitation = create_invitation(
        trainer_client,
        trainer_headers,
        "client-1@example.com",
        ["plans"],
    ).json()
    accept_invitation(trainer_client, client_headers, invitation["token"], ["plans"])
    link = trainer_client.get(
        "/api/v1/trainer/clients", headers=trainer_headers
    ).json()["items"][0]
    client_id = link["client_user_id"]

    plans = trainer_client.get(
        f"/api/v1/trainer/clients/{client_id}/plans", headers=trainer_headers
    )
    assert plans.status_code == 200

    workouts = trainer_client.get(
        f"/api/v1/trainer/clients/{client_id}/workouts", headers=trainer_headers
    )
    assert workouts.status_code == 403
    assert workouts.json()["error"]["code"] == "trainer_access_denied"

    feedback = trainer_client.get(
        f"/api/v1/trainer/clients/{client_id}/feedback", headers=trainer_headers
    )
    assert feedback.status_code == 403
    progress = trainer_client.get(
        f"/api/v1/trainer/clients/{client_id}/progress", headers=trainer_headers
    )
    assert progress.status_code == 403


@pytest.mark.integration
def test_cross_trainer_isolation(trainer_client, token_factory, db_session):
    trainer_a = make_trainer(trainer_client, db_session, token_factory, sub="trainer-a")
    trainer_b = make_trainer(trainer_client, db_session, token_factory, sub="trainer-b")
    client_headers = make_client(trainer_client, token_factory)
    invitation = create_invitation(
        trainer_client,
        trainer_a,
        "client-1@example.com",
        ["plans"],
    ).json()
    accept_invitation(trainer_client, client_headers, invitation["token"], ["plans"])
    client_id = trainer_client.get(
        "/api/v1/trainer/clients", headers=trainer_a
    ).json()["items"][0]["client_user_id"]

    assert trainer_client.get(
        "/api/v1/trainer/clients", headers=trainer_b
    ).json()["items"] == []
    forbidden = trainer_client.get(
        f"/api/v1/trainer/clients/{client_id}/plans", headers=trainer_b
    )
    assert forbidden.status_code == 404
    assert forbidden.json()["error"]["code"] == "trainer_client_not_found"


@pytest.mark.integration
def test_trainer_reads_client_plans_workouts_feedback_progress(
    trainer_client,
    token_factory,
    db_session,
):
    trainer_headers = make_trainer(trainer_client, db_session, token_factory)
    client_headers = make_client(trainer_client, token_factory)
    invitation = create_invitation(
        trainer_client,
        trainer_headers,
        "client-1@example.com",
        ["plans", "workouts", "feedback", "progress"],
    ).json()
    accept_invitation(
        trainer_client,
        client_headers,
        invitation["token"],
        ["plans", "workouts", "feedback", "progress"],
    )
    client_id = trainer_client.get(
        "/api/v1/trainer/clients", headers=trainer_headers
    ).json()["items"][0]["client_user_id"]

    plan = create_plan(trainer_client, client_headers).json()
    workout = start_and_complete(trainer_client, client_headers, plan["id"])
    trainer_client.post(
        "/api/v1/feedback",
        json={"plan_id": plan["id"], "rating": 4, "comment": "solid"},
        headers=client_headers,
    )

    plans = trainer_client.get(
        f"/api/v1/trainer/clients/{client_id}/plans", headers=trainer_headers
    )
    assert plans.status_code == 200
    assert len(plans.json()["items"]) == 1

    workouts = trainer_client.get(
        f"/api/v1/trainer/clients/{client_id}/workouts", headers=trainer_headers
    )
    assert workouts.status_code == 200
    assert workouts.json()["items"][0]["id"] == workout["id"]

    feedback = trainer_client.get(
        f"/api/v1/trainer/clients/{client_id}/feedback", headers=trainer_headers
    )
    assert feedback.status_code == 200
    assert feedback.json()["items"][0]["rating"] == 4

    progress = trainer_client.get(
        f"/api/v1/trainer/clients/{client_id}/progress?timezone=Asia/Jakarta",
        headers=trainer_headers,
    )
    assert progress.status_code == 200
    assert progress.json()["totals"]["workouts_completed"] == 1

    actions = set(db_session.scalars(select(AuditLog.action)).all())
    assert "trainer.client_plans_viewed" in actions
    assert "trainer.client_workouts_viewed" in actions
    assert "trainer.client_feedback_viewed" in actions
    assert "trainer.client_progress_viewed" in actions


@pytest.mark.integration
def test_comments_and_plan_review(trainer_client, token_factory, db_session):
    trainer_headers = make_trainer(trainer_client, db_session, token_factory)
    client_headers = make_client(trainer_client, token_factory)
    invitation = create_invitation(
        trainer_client,
        trainer_headers,
        "client-1@example.com",
        ["plans"],
    ).json()
    accept_invitation(trainer_client, client_headers, invitation["token"], ["plans"])
    client_id = trainer_client.get(
        "/api/v1/trainer/clients", headers=trainer_headers
    ).json()["items"][0]["client_user_id"]
    plan = create_plan(trainer_client, client_headers).json()

    comment = trainer_client.post(
        f"/api/v1/trainer/clients/{client_id}/comments",
        json={"body": "keep the first set easy", "plan_id": plan["id"]},
        headers=trainer_headers,
    )
    assert comment.status_code == 201, comment.text
    assert comment.json()["body"] == "keep the first set easy"

    review = trainer_client.patch(
        f"/api/v1/trainer/plans/{plan['id']}/review",
        json={"status": "approved", "note": "looks safe"},
        headers=trainer_headers,
    )
    assert review.status_code == 200, review.text
    assert review.json()["status"] == "approved"

    comments = trainer_client.get("/api/v1/me/trainer/comments", headers=client_headers)
    assert comments.status_code == 200
    assert comments.json()["items"][0]["body"] == "keep the first set easy"
    reviews = trainer_client.get("/api/v1/me/trainer/reviews", headers=client_headers)
    assert reviews.status_code == 200
    assert reviews.json()["items"][0]["status"] == "approved"


@pytest.mark.integration
def test_client_can_revoke_access(trainer_client, token_factory, db_session):
    trainer_headers = make_trainer(trainer_client, db_session, token_factory)
    client_headers = make_client(trainer_client, token_factory)
    invitation = create_invitation(
        trainer_client,
        trainer_headers,
        "client-1@example.com",
        ["plans"],
    ).json()
    accept_invitation(trainer_client, client_headers, invitation["token"], ["plans"])
    link = trainer_client.get(
        "/api/v1/trainer/clients", headers=trainer_headers
    ).json()["items"][0]

    revoked = trainer_client.delete(
        f"/api/v1/me/trainers/{link['trainer_user_id']}",
        headers=client_headers,
    )
    assert revoked.status_code == 204
    assert trainer_client.get(
        f"/api/v1/trainer/clients/{link['client_user_id']}/plans",
        headers=trainer_headers,
    ).status_code == 404
    assert trainer_client.get(
        "/api/v1/me/trainers", headers=client_headers
    ).json()["items"] == []


@pytest.mark.integration
def test_trainer_audit_has_no_email_or_notes(
    trainer_client,
    token_factory,
    db_session,
):
    trainer_headers = make_trainer(trainer_client, db_session, token_factory)
    client_headers = make_client(trainer_client, token_factory)
    invitation = create_invitation(
        trainer_client,
        trainer_headers,
        "client-1@example.com",
        ["plans"],
    ).json()
    accept_invitation(trainer_client, client_headers, invitation["token"], ["plans"])
    client_id = trainer_client.get(
        "/api/v1/trainer/clients", headers=trainer_headers
    ).json()["items"][0]["client_user_id"]
    plan = create_plan(trainer_client, client_headers).json()
    trainer_client.post(
        f"/api/v1/trainer/clients/{client_id}/comments",
        json={"body": "private trainer note", "plan_id": plan["id"]},
        headers=trainer_headers,
    )
    trainer_client.patch(
        f"/api/v1/trainer/plans/{plan['id']}/review",
        json={"status": "approved", "note": "private review note"},
        headers=trainer_headers,
    )

    serialized = " ".join(
        str(entry.metadata_json)
        for entry in db_session.scalars(select(AuditLog)).all()
    )
    assert "client-1@example.com" not in serialized
    assert "private trainer note" not in serialized
    assert "private review note" not in serialized


@pytest.mark.integration
def test_trainer_openapi(trainer_client):
    document = trainer_client.get("/openapi.json").json()
    paths = document["paths"]
    assert "/api/v1/trainer/profile" in paths
    assert "/api/v1/trainer/invitations" in paths
    assert "/api/v1/trainer/clients" in paths
    assert "/api/v1/trainer/clients/{client_id}/plans" in paths
    assert "/api/v1/trainer/clients/{client_id}/workouts" in paths
    assert "/api/v1/trainer/clients/{client_id}/feedback" in paths
    assert "/api/v1/trainer/clients/{client_id}/progress" in paths
    assert "/api/v1/trainer/clients/{client_id}/comments" in paths
    assert "/api/v1/trainer/plans/{plan_id}/review" in paths
    assert "/api/v1/me/trainers" in paths
