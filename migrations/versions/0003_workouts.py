"""P0.3 workout sessions, set logs, and offline mutations.

Revision ID: 0003_workouts
Revises: 0002_plans
Create Date: 2026-11-23
"""

from __future__ import annotations

from typing import Optional

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_workouts"
down_revision: Optional[str] = "0002_plans"
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


def _json_object_default():
    return sa.text("'{}'::jsonb") if _is_postgres() else sa.text("'{}'")


def upgrade() -> None:
    op.create_table(
        "workout_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "owner_user_id",
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
            "plan_version_id",
            sa.Uuid(),
            sa.ForeignKey("plan_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "plan_day_id",
            sa.Uuid(),
            sa.ForeignKey("plan_days.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("day_number", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("focus", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="in_progress",
        ),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("injuries", _json_type(), nullable=False, server_default=_json_list_default()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("client_session_id", sa.Uuid(), nullable=True),
        sa.Column("total_sets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_reps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_volume_kg", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0"),
        sa.Column("exercise_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('in_progress', 'completed', 'abandoned')",
            name="ck_workout_sessions_status",
        ),
    )
    op.create_index(
        "ix_workout_sessions_owner_started",
        "workout_sessions",
        ["owner_user_id", "started_at"],
    )
    op.create_index(
        "uq_workout_sessions_owner_client",
        "workout_sessions",
        ["owner_user_id", "client_session_id"],
        unique=True,
        postgresql_where=sa.text("client_session_id IS NOT NULL"),
        sqlite_where=sa.text("client_session_id IS NOT NULL"),
    )

    op.create_table(
        "workout_exercises",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "workout_session_id",
            sa.Uuid(),
            sa.ForeignKey("workout_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_plan_exercise_id",
            sa.Uuid(),
            sa.ForeignKey("plan_exercises.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("exercise_id", sa.String(length=64), nullable=False),
        sa.Column("exercise_name", sa.String(length=255), nullable=False),
        sa.Column("body_part", sa.String(length=32), nullable=False),
        sa.Column("equipment", _json_type(), nullable=False),
        sa.Column("primary_muscle", _json_type(), nullable=False),
        sa.Column("secondary_muscle", _json_type(), nullable=False, server_default=_json_list_default()),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("substituted_from_exercise_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint(
            "workout_session_id",
            "position",
            name="uq_workout_exercises_session_position",
        ),
    )
    op.create_index(
        "ix_workout_exercises_session",
        "workout_exercises",
        ["workout_session_id"],
    )

    op.create_table(
        "set_logs",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "workout_exercise_id",
            sa.Uuid(),
            sa.ForeignKey("workout_exercises.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("set_number", sa.Integer(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=True),
        sa.Column("weight_kg", sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column("rpe", sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("client_set_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("set_number >= 1", name="ck_set_logs_set_number"),
        sa.CheckConstraint("reps IS NULL OR reps >= 0", name="ck_set_logs_reps"),
        sa.CheckConstraint("weight_kg IS NULL OR weight_kg >= 0", name="ck_set_logs_weight"),
        sa.CheckConstraint(
            "rpe IS NULL OR (rpe >= 1 AND rpe <= 10)",
            name="ck_set_logs_rpe",
        ),
    )
    op.create_index(
        "uq_set_logs_owner_client",
        "set_logs",
        ["owner_user_id", "client_set_id"],
        unique=True,
        postgresql_where=sa.text("client_set_id IS NOT NULL"),
        sqlite_where=sa.text("client_set_id IS NOT NULL"),
    )
    op.create_index(
        "uq_set_logs_exercise_set",
        "set_logs",
        ["workout_exercise_id", "set_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_set_logs_workout_exercise", "set_logs", ["workout_exercise_id"])

    op.create_table(
        "client_mutations",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_mutation_id", sa.String(length=64), nullable=False),
        sa.Column("mutation_type", sa.String(length=32), nullable=False),
        sa.Column("result", _json_type(), nullable=False, server_default=_json_object_default()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint(
            "owner_user_id",
            "client_mutation_id",
            name="uq_client_mutations_owner_client",
        ),
    )
    op.create_index(
        "ix_client_mutations_owner",
        "client_mutations",
        ["owner_user_id"],
    )


def downgrade() -> None:
    op.drop_table("client_mutations")
    op.drop_table("set_logs")
    op.drop_table("workout_exercises")
    op.drop_table("workout_sessions")
