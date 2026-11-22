"""Integration tests for P2.1 free organizations and memberships."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    AuditLog,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    User,
)
from app.main import create_app

SECRET = "test-secret-" + ("x" * 40)
ISSUER = "https://issuer.test"
AUDIENCE = "fitness-api-test"


@pytest.fixture()
def org_settings(dataset_path: Path, tmp_path: Path) -> Settings:
    database_path = (tmp_path / "organizations.db").as_posix()
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
        notifications_enabled=False,
        organizations_enabled=True,
        auth_dev_mode=True,
        auth_dev_secret=SECRET,
        auth_issuer=ISSUER,
        auth_audience=AUDIENCE,
    )


@pytest.fixture()
def org_app(org_settings: Settings):
    return create_app(org_settings)


@pytest.fixture()
def org_client(org_app):
    with TestClient(org_app) as client:
        yield client


@pytest.fixture()
def db_session(org_client, org_app) -> Session:
    session = org_app.state.session_factory()
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


def headers_for(client, token_factory, sub: str, email: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token_factory(sub, email)}"}
    assert client.get("/api/v1/me", headers=headers).status_code == 200
    return headers


def create_org(client, headers, **overrides) -> dict:
    payload = {
        "name": overrides.pop("name", "Garuda Gym"),
        "type": overrides.pop("type", "gym"),
        "description": "Tempat latihan",
        "website": "https://garuda.example",
        "timezone": "Asia/Jakarta",
        "branding": {"primary_color": "#123456"},
        **overrides,
    }
    response = client.post("/api/v1/orgs", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def invite(client, headers, org_id: str, email: str, role: str = "member"):
    return client.post(
        f"/api/v1/orgs/{org_id}/invitations",
        json={"email": email, "role": role},
        headers=headers,
    )


def accept_path(invite_url: str) -> str:
    return urlparse(invite_url).path


@pytest.mark.integration
def test_organizations_are_feature_flagged(client):
    assert client.get("/api/v1/me/orgs").status_code == 404
    assert client.post("/api/v1/orgs", json={"name": "X"}).status_code == 404


@pytest.mark.integration
def test_create_organization_and_slug(org_client, token_factory):
    owner = headers_for(org_client, token_factory, "owner-1")
    org = create_org(org_client, owner)
    assert org["role"] == "owner"
    assert org["slug"] == "garuda-gym"
    assert org["timezone"] == "Asia/Jakarta"
    assert org["branding"] == {"primary_color": "#123456"}

    second = create_org(org_client, owner, name="Garuda Gym")
    assert second["slug"] == "garuda-gym-2"

    listed = org_client.get("/api/v1/me/orgs", headers=owner)
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 2

    detail = org_client.get(f"/api/v1/orgs/{org['id']}", headers=owner)
    assert detail.status_code == 200
    assert detail.json()["id"] == org["id"]


@pytest.mark.integration
def test_invalid_organization_payload(org_client, token_factory):
    owner = headers_for(org_client, token_factory, "owner-1")
    invalid_slug = org_client.post(
        "/api/v1/orgs",
        json={"name": "Bad Slug", "slug": "Bad Slug"},
        headers=owner,
    )
    assert invalid_slug.status_code == 422

    invalid_timezone = org_client.post(
        "/api/v1/orgs",
        json={"name": "Bad Time", "timezone": "Mars/Olympus"},
        headers=owner,
    )
    assert invalid_timezone.status_code == 422


@pytest.mark.integration
def test_admin_update_and_member_cannot_update(org_client, token_factory, db_session):
    owner = headers_for(org_client, token_factory, "owner-1")
    member = headers_for(org_client, token_factory, "member-1")
    org = create_org(org_client, owner)
    invitation = invite(org_client, owner, org["id"], "member-1@example.com")
    assert invitation.status_code == 201, invitation.text
    token = invitation.json()["token"]
    accepted = org_client.post(
        f"/api/v1/org-invitations/{token}/accept", headers=member
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["role"] == "member"

    updated = org_client.patch(
        f"/api/v1/orgs/{org['id']}",
        json={"name": "Garuda Gym Baru", "timezone": "Asia/Makassar"},
        headers=owner,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Garuda Gym Baru"
    assert updated.json()["timezone"] == "Asia/Makassar"

    forbidden = org_client.patch(
        f"/api/v1/orgs/{org['id']}",
        json={"name": "Hijack"},
        headers=member,
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "organization_access_denied"

    outsider = headers_for(org_client, token_factory, "outsider-1")
    missing = org_client.get(f"/api/v1/orgs/{org['id']}", headers=outsider)
    assert missing.status_code == 404
    denied_members = org_client.get(
        f"/api/v1/orgs/{org['id']}/members", headers=outsider
    )
    assert denied_members.status_code == 404


@pytest.mark.integration
def test_invitation_accept_and_decline(org_client, token_factory, db_session):
    owner = headers_for(org_client, token_factory, "owner-1")
    invited = headers_for(org_client, token_factory, "invitee-1")
    org = create_org(org_client, owner)

    invitation = invite(
        org_client, owner, org["id"], "invitee-1@example.com", role="trainer"
    )
    assert invitation.status_code == 201, invitation.text
    body = invitation.json()
    assert body["role"] == "trainer"
    assert body["token"]
    assert body["invite_url"].endswith(f"/api/v1/org-invitations/{body['token']}/accept")

    # Only a hash is stored; the raw token is shown once.
    stored = db_session.scalar(
        select(OrganizationInvitation).where(
            OrganizationInvitation.id == uuid.UUID(body["id"])
        )
    )
    assert stored is not None
    assert stored.token_hash != body["token"]

    accepted = org_client.post(
        f"/api/v1/org-invitations/{body['token']}/accept", headers=invited
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["id"] == org["id"]
    assert accepted.json()["role"] == "trainer"

    members = org_client.get(f"/api/v1/orgs/{org['id']}/members", headers=owner)
    assert members.status_code == 200
    assert len(members.json()["items"]) == 2
    roles = {item["role"] for item in members.json()["items"]}
    assert roles == {"owner", "trainer"}

    # The same invitation cannot be accepted twice.
    replay = org_client.post(
        f"/api/v1/org-invitations/{body['token']}/accept", headers=invited
    )
    assert replay.status_code == 404

    decliner = headers_for(org_client, token_factory, "decliner-1")
    decline_invite = invite(
        org_client, owner, org["id"], "decliner-1@example.com", role="member"
    )
    assert decline_invite.status_code == 201
    decline_token = decline_invite.json()["token"]
    declined = org_client.post(
        f"/api/v1/org-invitations/{decline_token}/decline", headers=decliner
    )
    assert declined.status_code == 204
    assert (
        org_client.post(
            f"/api/v1/org-invitations/{decline_token}/accept", headers=decliner
        ).status_code
        == 404
    )


@pytest.mark.integration
def test_invitation_email_mismatch_and_duplicate(org_client, token_factory):
    owner = headers_for(org_client, token_factory, "owner-1")
    someone_else = headers_for(org_client, token_factory, "someone-1")
    org = create_org(org_client, owner)

    invitation = invite(org_client, owner, org["id"], "target-1@example.com")
    assert invitation.status_code == 201
    token = invitation.json()["token"]

    mismatch = org_client.post(
        f"/api/v1/org-invitations/{token}/accept", headers=someone_else
    )
    assert mismatch.status_code == 403

    duplicate = invite(org_client, owner, org["id"], "target-1@example.com")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "organization_invitation_conflict"

    owner_as_invitee = invite(org_client, owner, org["id"], "owner-1@example.com")
    assert owner_as_invitee.status_code == 409


@pytest.mark.integration
def test_member_cannot_invite(org_client, token_factory):
    owner = headers_for(org_client, token_factory, "owner-1")
    member = headers_for(org_client, token_factory, "member-1")
    org = create_org(org_client, owner)
    created = invite(org_client, owner, org["id"], "member-1@example.com")
    assert created.status_code == 201
    assert (
        org_client.post(
            f"/api/v1/org-invitations/{created.json()['token']}/accept",
            headers=member,
        ).status_code
        == 200
    )

    forbidden = invite(org_client, member, org["id"], "other@example.com")
    assert forbidden.status_code == 403


@pytest.mark.integration
def test_expired_invitation(org_client, token_factory, db_session):
    owner = headers_for(org_client, token_factory, "owner-1")
    late = headers_for(org_client, token_factory, "late-1")
    org = create_org(org_client, owner)
    invitation = invite(org_client, owner, org["id"], "late-1@example.com")
    assert invitation.status_code == 201
    stored = db_session.get(
        OrganizationInvitation, uuid.UUID(invitation.json()["id"])
    )
    assert stored is not None
    stored.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    response = org_client.post(
        f"/api/v1/org-invitations/{invitation.json()['token']}/accept",
        headers=late,
    )
    assert response.status_code == 404
    db_session.refresh(stored)
    assert stored.status == "expired"

    stale = invite(org_client, owner, org["id"], "late-2@example.com")
    assert stale.status_code == 201
    stale_row = db_session.get(
        OrganizationInvitation, uuid.UUID(stale.json()["id"])
    )
    assert stale_row is not None
    stale_row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    listed = org_client.get(f"/api/v1/orgs/{org['id']}/invitations", headers=owner)
    assert listed.status_code == 200
    statuses = {
        item["email"]: item["status"] for item in listed.json()["items"]
    }
    assert statuses["late-2@example.com"] == "expired"


@pytest.mark.integration
def test_role_changes_and_owner_protection(org_client, token_factory):
    owner = headers_for(org_client, token_factory, "owner-1")
    admin = headers_for(org_client, token_factory, "admin-1")
    org = create_org(org_client, owner)

    admin_invite = invite(
        org_client, owner, org["id"], "admin-1@example.com", role="admin"
    )
    assert admin_invite.status_code == 201
    assert (
        org_client.post(
            f"/api/v1/org-invitations/{admin_invite.json()['token']}/accept",
            headers=admin,
        ).status_code
        == 200
    )

    admin_user = db_session_user_id(org_client, "admin-1")
    promoter = org_client.patch(
        f"/api/v1/orgs/{org['id']}/members/{admin_user}",
        json={"role": "owner"},
        headers=admin,
    )
    assert promoter.status_code == 403
    assert promoter.json()["error"]["code"] == "organization_access_denied"

    demote_self = org_client.patch(
        f"/api/v1/orgs/{org['id']}/members/{admin_user}",
        json={"role": "member"},
        headers=admin,
    )
    assert demote_self.status_code == 200
    assert {item["role"] for item in demote_self.json()["items"]} == {
        "owner",
        "member",
    }

    owner_id = db_session_user_id(org_client, "owner-1")
    last_owner = org_client.delete(
        f"/api/v1/orgs/{org['id']}/members/{owner_id}", headers=owner
    )
    assert last_owner.status_code == 409
    assert last_owner.json()["error"]["code"] == "organization_conflict"


def db_session_user_id(client, sub: str) -> str:
    session = client.app.state.session_factory()
    try:
        user = session.scalar(select(User).where(User.auth_subject == sub))
        assert user is not None
        return str(user.id)
    finally:
        session.close()


@pytest.mark.integration
def test_remove_member_and_leave(org_client, token_factory):
    owner = headers_for(org_client, token_factory, "owner-1")
    member = headers_for(org_client, token_factory, "member-1")
    org = create_org(org_client, owner)
    created = invite(org_client, owner, org["id"], "member-1@example.com")
    assert created.status_code == 201
    assert (
        org_client.post(
            f"/api/v1/org-invitations/{created.json()['token']}/accept",
            headers=member,
        ).status_code
        == 200
    )
    member_id = db_session_user_id(org_client, "member-1")

    removed = org_client.delete(
        f"/api/v1/orgs/{org['id']}/members/{member_id}", headers=owner
    )
    assert removed.status_code == 204
    assert (
        org_client.get(f"/api/v1/orgs/{org['id']}", headers=member).status_code
        == 404
    )
    assert (
        org_client.get(f"/api/v1/orgs/{org['id']}/members", headers=owner)
        .json()["items"]
    )

    second = headers_for(org_client, token_factory, "second-1")
    second_invite = invite(
        org_client, owner, org["id"], "second-1@example.com", role="trainer"
    )
    assert second_invite.status_code == 201
    assert (
        org_client.post(
            f"/api/v1/org-invitations/{second_invite.json()['token']}/accept",
            headers=second,
        ).status_code
        == 200
    )
    left = org_client.post(f"/api/v1/orgs/{org['id']}/leave", headers=second)
    assert left.status_code == 204
    assert (
        org_client.get(f"/api/v1/orgs/{org['id']}", headers=second).status_code
        == 404
    )


@pytest.mark.integration
def test_org_isolation_and_summary(org_client, token_factory, db_session):
    owner_a = headers_for(org_client, token_factory, "owner-a")
    owner_b = headers_for(org_client, token_factory, "owner-b")
    member = headers_for(org_client, token_factory, "member-1")
    org_a = create_org(org_client, owner_a, name="Alpha Gym")
    org_b = create_org(org_client, owner_b, name="Beta Gym")

    invitation = invite(
        org_client, owner_a, org_a["id"], "member-1@example.com", role="trainer"
    )
    assert (
        org_client.post(
            f"/api/v1/org-invitations/{invitation.json()['token']}/accept",
            headers=member,
        ).status_code
        == 200
    )

    # Cross-org access is indistinguishable from a missing org.
    assert (
        org_client.get(f"/api/v1/orgs/{org_b['id']}", headers=member).status_code
        == 404
    )
    assert (
        org_client.get(
            f"/api/v1/orgs/{org_b['id']}/members", headers=member
        ).status_code
        == 404
    )

    summary = org_client.get(f"/api/v1/orgs/{org_a['id']}/summary", headers=owner_a)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["members_total"] == 2
    assert body["trainers"] == 1
    assert body["clients"] == 0
    assert body["active_plans"] == 0

    member_summary = org_client.get(
        f"/api/v1/orgs/{org_a['id']}/summary", headers=member
    )
    assert member_summary.status_code == 403

    assert (
        org_client.get(f"/api/v1/orgs/{org_a['id']}", headers=owner_a).json()[
            "role"
        ]
        == "owner"
    )

    # Members cannot be listed from another organization.
    assert (
        org_client.get(
            f"/api/v1/orgs/{org_b['id']}/summary", headers=owner_a
        ).status_code
        == 404
    )


@pytest.mark.integration
def test_invitation_listing_is_admin_only(org_client, token_factory):
    owner = headers_for(org_client, token_factory, "owner-1")
    member = headers_for(org_client, token_factory, "member-1")
    org = create_org(org_client, owner)
    created = invite(org_client, owner, org["id"], "member-1@example.com")
    assert (
        org_client.post(
            f"/api/v1/org-invitations/{created.json()['token']}/accept",
            headers=member,
        ).status_code
        == 200
    )
    pending = invite(org_client, owner, org["id"], "pending@example.com")
    assert pending.status_code == 201

    listed = org_client.get(f"/api/v1/orgs/{org['id']}/invitations", headers=owner)
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 2

    forbidden = org_client.get(
        f"/api/v1/orgs/{org['id']}/invitations", headers=member
    )
    assert forbidden.status_code == 403


@pytest.mark.integration
def test_audit_entries_are_pii_free(org_client, token_factory, db_session):
    owner = headers_for(org_client, token_factory, "owner-1")
    org = create_org(org_client, owner)
    invite(org_client, owner, org["id"], "member-1@example.com")

    entries = list(db_session.scalars(select(AuditLog).order_by(AuditLog.created_at)).all())
    actions = {entry.action for entry in entries}
    assert "organization.created" in actions
    assert "organization.invitation_created" in actions
    for entry in entries:
        text = str(entry.metadata_json)
        assert "@example.com" not in text
        assert "token" not in text.lower()

    total = db_session.scalar(
        select(func.count(OrganizationMembership.id)).where(
            OrganizationMembership.status == "active"
        )
    )
    assert total == 1
    stored_org = db_session.scalar(select(Organization))
    assert stored_org is not None


@pytest.mark.integration
def test_organization_openapi(org_client):
    document = org_client.get("/openapi.json").json()
    paths = document["paths"]
    assert "/api/v1/orgs" in paths
    assert "/api/v1/me/orgs" in paths
    assert "/api/v1/orgs/{org_id}" in paths
    assert "/api/v1/orgs/{org_id}/members" in paths
    assert "/api/v1/orgs/{org_id}/members/{user_id}" in paths
    assert "/api/v1/orgs/{org_id}/invitations" in paths
    assert "/api/v1/orgs/{org_id}/summary" in paths
    assert "/api/v1/org-invitations/{token}/accept" in paths
    assert "/api/v1/org-invitations/{token}/decline" in paths
