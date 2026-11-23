"""P2.2 research events, experiments, versions, and quality reviews.

Revision ID: 0009_research
Revises: 0008_organizations
Create Date: 2026-11-23
"""

from __future__ import annotations

from typing import Optional

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_research"
down_revision: Optional[str] = "0008_organizations"
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


def _json_list_default():
    return sa.text("'[]'::jsonb") if _is_postgres() else sa.text("'[]'")


def upgrade() -> None:
    op.create_table(
        "research_events",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "properties",
            _json_type(),
            nullable=False,
            server_default=_json_object_default(),
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_now_default(),
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_now_default(),
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_now_default(),
        ),
    )
    op.create_index(
        "uq_research_events_owner_idempotency",
        "research_events",
        ["owner_user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "ix_research_events_owner_occurred",
        "research_events",
        ["owner_user_id", "occurred_at"],
    )
    op.create_index(
        "ix_research_events_name_occurred",
        "research_events",
        ["name", "occurred_at"],
    )

    op.create_table(
        "experiments",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column(
            "variants",
            _json_type(),
            nullable=False,
            server_default=_json_list_default(),
        ),
        sa.Column(
            "traffic_percent", sa.Integer(), nullable=False, server_default="100"
        ),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_now_default(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_now_default(),
        ),
        sa.UniqueConstraint("key", name="uq_experiments_key"),
        sa.CheckConstraint(
            "status IN ('draft', 'running', 'paused', 'completed')",
            name="ck_experiments_status",
        ),
        sa.CheckConstraint(
            "traffic_percent >= 0 AND traffic_percent <= 100",
            name="ck_experiments_traffic",
        ),
    )
    op.create_index("ix_experiments_status", "experiments", ["status"])

    op.create_table(
        "experiment_assignments",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "experiment_id",
            sa.Uuid(),
            sa.ForeignKey("experiments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("variant", sa.String(length=64), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_now_default(),
        ),
        sa.Column("exposed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "experiment_id",
            "user_id",
            name="uq_experiment_assignments_experiment_user",
        ),
    )
    op.create_index(
        "ix_experiment_assignments_user",
        "experiment_assignments",
        ["user_id"],
    )
    op.create_index(
        "ix_experiment_assignments_experiment_variant",
        "experiment_assignments",
        ["experiment_id", "variant"],
    )

    op.create_table(
        "research_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column(
            "metadata_json",
            _json_type(),
            nullable=False,
            server_default=_json_object_default(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_now_default(),
        ),
        sa.UniqueConstraint(
            "kind",
            "version",
            name="uq_research_versions_kind_version",
        ),
        sa.CheckConstraint(
            "kind IN ('dataset', 'algorithm')",
            name="ck_research_versions_kind",
        ),
    )
    op.create_index(
        "ix_research_versions_kind_created",
        "research_versions",
        ["kind", "created_at"],
    )

    op.create_table(
        "quality_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "reviewer_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject_type", sa.String(length=24), nullable=False),
        sa.Column("subject_id", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=24), nullable=False, server_default="pending"
        ),
        sa.Column(
            "rubric",
            _json_type(),
            nullable=False,
            server_default=_json_object_default(),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_now_default(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_now_default(),
        ),
        sa.CheckConstraint(
            "subject_type IN ('plan_version', 'dataset_version', 'algorithm_version')",
            name="ck_quality_reviews_subject_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'in_review', 'approved', 'changes_requested')",
            name="ck_quality_reviews_status",
        ),
    )
    op.create_index(
        "ix_quality_reviews_subject",
        "quality_reviews",
        ["subject_type", "subject_id"],
    )
    op.create_index("ix_quality_reviews_status", "quality_reviews", ["status"])


def downgrade() -> None:
    op.drop_table("quality_reviews")
    op.drop_table("research_versions")
    op.drop_table("experiment_assignments")
    op.drop_table("experiments")
    op.drop_table("research_events")
