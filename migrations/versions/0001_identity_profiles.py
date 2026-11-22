"""P0.1 identity, profiles, consent, roles, and audit.

Revision ID: 0001_identity_profiles
Revises:
Create Date: 2026-11-22
"""

from __future__ import annotations

from typing import Optional

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_identity_profiles"
down_revision: Optional[str] = None
branch_labels = None
depends_on = None


def _dialect_name() -> str:
    return op.get_context().dialect.name


def _is_postgres() -> bool:
    return _dialect_name() == "postgresql"


def _json_type():
    return postgresql.JSONB() if _is_postgres() else sa.JSON()


def _text_array_type():
    return postgresql.ARRAY(sa.Text()) if _is_postgres() else sa.JSON()


def _now_default():
    return sa.text("now()") if _is_postgres() else sa.text("CURRENT_TIMESTAMP")


def _uuid_default():
    return sa.text("gen_random_uuid()") if _is_postgres() else None


def _json_default():
    return sa.text("'{}'::jsonb") if _is_postgres() else sa.text("'{}'")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column("auth_issuer", sa.String(length=255), nullable=False),
        sa.Column("auth_subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deletion_scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("auth_issuer", "auth_subject", name="uq_users_auth_identity"),
    )
    op.create_index("ix_users_email_lower", "users", [sa.text("lower(email)")])

    op.create_table(
        "profiles",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("gender", sa.String(length=16), nullable=True),
        sa.Column("height_cm", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("weight_kg", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("goal", sa.String(length=32), nullable=True),
        sa.Column("experience", sa.String(length=16), nullable=True),
        sa.Column("session_minutes", sa.Integer(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("locale", sa.String(length=16), nullable=True),
        sa.Column("unit_system", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.CheckConstraint("gender IN ('male', 'female')", name="ck_profiles_gender"),
        sa.CheckConstraint(
            "goal IN ('muscle_gain', 'fat_loss', 'general_health')",
            name="ck_profiles_goal",
        ),
        sa.CheckConstraint(
            "experience IN ('beginner', 'intermediate', 'advanced')",
            name="ck_profiles_experience",
        ),
        sa.CheckConstraint(
            "session_minutes IN (30, 45, 60, 90)",
            name="ck_profiles_session_minutes",
        ),
        sa.CheckConstraint(
            "unit_system IN ('metric', 'imperial')",
            name="ck_profiles_unit_system",
        ),
    )

    op.create_table(
        "user_equipment",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("equipment", sa.String(length=64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
    )

    op.create_table(
        "user_injuries",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("term", sa.String(length=60), nullable=False),
        sa.Column("body_parts", _text_array_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint("user_id", "term", name="uq_user_injuries_user_term"),
    )
    op.create_index("ix_user_injuries_user_id", "user_injuries", ["user_id"])

    op.create_table(
        "consents",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.CheckConstraint(
            "kind IN ('health_data_processing', 'research_analytics', "
            "'trainer_sharing', 'marketing')",
            name="ck_consents_kind",
        ),
    )
    op.create_index(
        "ix_consents_user_kind_granted",
        "consents",
        ["user_id", "kind", "granted_at"],
    )

    op.create_table(
        "user_roles",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column(
            "granted_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "role IN ('user', 'trainer', 'org_admin', 'platform_admin')",
            name="ck_user_roles_role",
        ),
        sa.UniqueConstraint("user_id", "role", "org_id", name="uq_user_roles_user_role_org"),
    )
    op.create_index(
        "uq_user_roles_user_role_platform",
        "user_roles",
        ["user_id", "role"],
        unique=True,
        postgresql_where=sa.text("org_id IS NULL"),
        sqlite_where=sa.text("org_id IS NULL"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_role", sa.String(length=100), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=True),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("metadata", _json_type(), nullable=False, server_default=_json_default()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
    )
    op.create_index(
        "ix_audit_log_actor_created",
        "audit_log",
        ["actor_user_id", "created_at"],
    )
    op.create_index(
        "ix_audit_log_resource",
        "audit_log",
        ["resource_type", "resource_id"],
    )
    op.create_index("ix_audit_log_created", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("user_roles")
    op.drop_table("consents")
    op.drop_table("user_injuries")
    op.drop_table("user_equipment")
    op.drop_table("profiles")
    op.drop_table("users")
