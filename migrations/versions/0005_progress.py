"""P1.1 progress aggregates, personal records, and weekly reviews.

Revision ID: 0005_progress
Revises: 0004_feedback
Create Date: 2026-11-23
"""

from __future__ import annotations

from typing import Optional

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_progress"
down_revision: Optional[str] = "0004_feedback"
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


def _json_object_default():
    return sa.text("'{}'::jsonb") if _is_postgres() else sa.text("'{}'")


def upgrade() -> None:
    op.create_table(
        "daily_metrics",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("workouts_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_sets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_reps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_volume_kg", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0"),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sets_by_body_part", _json_type(), nullable=False, server_default=_json_object_default()),
        sa.Column("volume_by_body_part", _json_type(), nullable=False, server_default=_json_object_default()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint(
            "owner_user_id",
            "metric_date",
            name="uq_daily_metrics_owner_date",
        ),
    )
    op.create_index(
        "ix_daily_metrics_owner_date",
        "daily_metrics",
        ["owner_user_id", "metric_date"],
    )

    op.create_table(
        "personal_records",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("exercise_id", sa.String(length=64), nullable=False),
        sa.Column("exercise_name", sa.String(length=255), nullable=False),
        sa.Column("record_type", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=True),
        sa.Column("weight_kg", sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column("achieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "set_log_id",
            sa.Uuid(),
            sa.ForeignKey("set_logs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint(
            "owner_user_id",
            "exercise_id",
            "record_type",
            name="uq_personal_records_owner_exercise_type",
        ),
        sa.CheckConstraint(
            "record_type IN ('max_weight', 'max_reps', 'max_volume')",
            name="ck_personal_records_type",
        ),
    )
    op.create_index("ix_personal_records_owner", "personal_records", ["owner_user_id"])

    op.create_table(
        "weekly_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("workouts_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_sets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_reps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_volume_kg", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0"),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sets_by_body_part", _json_type(), nullable=False, server_default=_json_object_default()),
        sa.Column("volume_by_body_part", _json_type(), nullable=False, server_default=_json_object_default()),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint(
            "owner_user_id",
            "week_start",
            name="uq_weekly_reviews_owner_week",
        ),
    )
    op.create_index(
        "ix_weekly_reviews_owner_week",
        "weekly_reviews",
        ["owner_user_id", "week_start"],
    )


def downgrade() -> None:
    op.drop_table("weekly_reviews")
    op.drop_table("personal_records")
    op.drop_table("daily_metrics")
