"""P0.2 plan persistence, versions, and shares.

Revision ID: 0002_plans
Revises: 0001_identity_profiles
Create Date: 2026-11-22
"""

from __future__ import annotations

from typing import Optional

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_plans"
down_revision: Optional[str] = "0001_identity_profiles"
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
        "plans",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("input_snapshot", _json_type(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("split_type", sa.String(length=32), nullable=False),
        sa.Column("day_count", sa.Integer(), nullable=False),
        sa.Column("bmi", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("bmi_category", sa.String(length=32), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("idempotency_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'archived', 'deleted')",
            name="ck_plans_status",
        ),
    )
    op.create_index("ix_plans_owner_created", "plans", ["owner_user_id", "created_at"])
    op.create_index(
        "uq_plans_owner_idempotency",
        "plans",
        ["owner_user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "plan_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("split_type", sa.String(length=32), nullable=False),
        sa.Column("schedule", _json_type(), nullable=False),
        sa.Column("warnings", _json_type(), nullable=False, server_default=_json_list_default()),
        sa.Column("day_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("plan_id", "version", name="uq_plan_versions_plan_version"),
    )
    op.create_index("ix_plan_versions_plan_id", "plan_versions", ["plan_id"])

    op.create_table(
        "plan_days",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "plan_version_id",
            sa.Uuid(),
            sa.ForeignKey("plan_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("focus", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint("plan_version_id", "day_number", name="uq_plan_days_version_day"),
        sa.CheckConstraint("day_number > 0", name="ck_plan_days_day_number"),
    )

    op.create_table(
        "plan_exercises",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "plan_day_id",
            sa.Uuid(),
            sa.ForeignKey("plan_days.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("exercise_id", sa.String(length=64), nullable=False),
        sa.Column("exercise_name", sa.String(length=255), nullable=False),
        sa.Column("body_part", sa.String(length=32), nullable=False),
        sa.Column("equipment", _json_type(), nullable=False),
        sa.Column("primary_muscle", _json_type(), nullable=False),
        sa.Column("secondary_muscle", _json_type(), nullable=False, server_default=_json_list_default()),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint("plan_day_id", "position", name="uq_plan_exercises_day_position"),
        sa.CheckConstraint("position >= 0", name="ck_plan_exercises_position"),
    )
    op.create_index("ix_plan_exercises_day_id", "plan_exercises", ["plan_day_id"])

    op.create_table(
        "plan_shares",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint("token_hash", name="uq_plan_shares_token_hash"),
    )
    op.create_index(
        "ix_plan_shares_plan_expires",
        "plan_shares",
        ["plan_id", "expires_at"],
    )


def downgrade() -> None:
    op.drop_table("plan_shares")
    op.drop_table("plan_exercises")
    op.drop_table("plan_days")
    op.drop_table("plan_versions")
    op.drop_table("plans")
