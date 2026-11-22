"""P0.4 feedback and safety reports.

Revision ID: 0004_feedback
Revises: 0003_workouts
Create Date: 2026-11-23
"""

from __future__ import annotations

from typing import Optional

import sqlalchemy as sa
from alembic import op

revision = "0004_feedback"
down_revision: Optional[str] = "0003_workouts"
branch_labels = None
depends_on = None


def _dialect_name() -> str:
    return op.get_context().dialect.name


def _is_postgres() -> bool:
    return _dialect_name() == "postgresql"


def _now_default():
    return sa.text("now()") if _is_postgres() else sa.text("CURRENT_TIMESTAMP")


def _uuid_default():
    return sa.text("gen_random_uuid()") if _is_postgres() else None


def upgrade() -> None:
    op.create_table(
        "feedback",
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
            "workout_session_id",
            sa.Uuid(),
            sa.ForeignKey("workout_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("difficulty", sa.String(length=16), nullable=True),
        sa.Column("pain", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("pain_area", sa.String(length=60), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.CheckConstraint(
            "rating IS NULL OR (rating >= 1 AND rating <= 5)",
            name="ck_feedback_rating",
        ),
        sa.CheckConstraint(
            "difficulty IS NULL OR difficulty IN ('too_easy', 'just_right', 'too_hard')",
            name="ck_feedback_difficulty",
        ),
    )
    op.create_index(
        "ix_feedback_owner_created",
        "feedback",
        ["owner_user_id", "created_at"],
    )
    op.create_index("ix_feedback_plan", "feedback", ["plan_id"])

    op.create_table(
        "unsafe_reports",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "reporter_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("plans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "plan_exercise_id",
            sa.Uuid(),
            sa.ForeignKey("plan_exercises.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "workout_session_id",
            sa.Uuid(),
            sa.ForeignKey("workout_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("exercise_id", sa.String(length=64), nullable=False),
        sa.Column("exercise_name", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "resolved_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_unsafe_reports_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'triaged', 'resolved', 'dismissed')",
            name="ck_unsafe_reports_status",
        ),
    )
    op.create_index(
        "ix_unsafe_reports_status_created",
        "unsafe_reports",
        ["status", "created_at"],
    )
    op.create_index("ix_unsafe_reports_severity", "unsafe_reports", ["severity"])
    op.create_index(
        "ix_unsafe_reports_reporter_created",
        "unsafe_reports",
        ["reporter_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("unsafe_reports")
    op.drop_table("feedback")
