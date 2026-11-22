"""P1.2 trainer workspace, invitations, grants, reviews, and comments.

Revision ID: 0006_trainer
Revises: 0005_progress
Create Date: 2026-11-23
"""

from __future__ import annotations

from typing import Optional

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_trainer"
down_revision: Optional[str] = "0005_progress"
branch_labels = None
depends_on = None


def _dialect_name() -> str:
    return op.get_context().dialect.name


def _is_postgres() -> bool:
    return _dialect_name() == "postgresql"


def _json_type():
    return postgresql.JSONB() if _is_postgres() else sa.JSON()


def _now_default():
    return sa.text("now()") if _is_postgres() else sa.text("CURRENT_TIMESTAMP")


def _uuid_default():
    return sa.text("gen_random_uuid()") if _is_postgres() else None


def _json_list_default():
    return sa.text("'[]'::jsonb") if _is_postgres() else sa.text("'[]'")


def upgrade() -> None:
    op.create_table(
        "trainer_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("specialties", _json_type(), nullable=False, server_default=_json_list_default()),
        sa.Column("years_experience", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint("user_id", name="uq_trainer_profiles_user"),
    )

    op.create_table(
        "trainer_clients",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "trainer_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "trainer_user_id",
            "client_user_id",
            name="uq_trainer_clients_pair",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_trainer_clients_status",
        ),
    )
    op.create_index("ix_trainer_clients_trainer", "trainer_clients", ["trainer_user_id"])
    op.create_index("ix_trainer_clients_client", "trainer_clients", ["client_user_id"])

    op.create_table(
        "trainer_invitations",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "trainer_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("client_email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("requested_scopes", _json_type(), nullable=False, server_default=_json_list_default()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint("token_hash", name="uq_trainer_invitations_token"),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'revoked', 'expired')",
            name="ck_trainer_invitations_status",
        ),
    )
    op.create_index(
        "ix_trainer_invitations_trainer",
        "trainer_invitations",
        ["trainer_user_id"],
    )
    op.create_index(
        "ix_trainer_invitations_email",
        "trainer_invitations",
        ["client_email"],
    )

    op.create_table(
        "access_grants",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "trainer_client_id",
            sa.Uuid(),
            sa.ForeignKey("trainer_clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint(
            "trainer_client_id",
            "scope",
            name="uq_access_grants_client_scope",
        ),
        sa.CheckConstraint(
            "scope IN ('plans', 'workouts', 'feedback', 'progress')",
            name="ck_access_grants_scope",
        ),
    )
    op.create_index("ix_access_grants_client", "access_grants", ["trainer_client_id"])

    op.create_table(
        "plan_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_version_id",
            sa.Uuid(),
            sa.ForeignKey("plan_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "trainer_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint(
            "plan_id",
            "trainer_user_id",
            name="uq_plan_reviews_plan_trainer",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'changes_requested')",
            name="ck_plan_reviews_status",
        ),
    )
    op.create_index("ix_plan_reviews_plan", "plan_reviews", ["plan_id"])
    op.create_index("ix_plan_reviews_trainer", "plan_reviews", ["trainer_user_id"])

    op.create_table(
        "trainer_comments",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "trainer_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("plans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "workout_session_id",
            sa.Uuid(),
            sa.ForeignKey("workout_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
    )
    op.create_index(
        "ix_trainer_comments_client_created",
        "trainer_comments",
        ["client_user_id", "created_at"],
    )
    op.create_index(
        "ix_trainer_comments_trainer_created",
        "trainer_comments",
        ["trainer_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("trainer_comments")
    op.drop_table("plan_reviews")
    op.drop_table("access_grants")
    op.drop_table("trainer_invitations")
    op.drop_table("trainer_clients")
    op.drop_table("trainer_profiles")
