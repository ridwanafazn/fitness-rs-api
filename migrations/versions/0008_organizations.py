"""P2.1 free organizations and membership (no billing).

Revision ID: 0008_organizations
Revises: 0007_notifications
Create Date: 2026-11-23
"""

from __future__ import annotations

from typing import Optional

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_organizations"
down_revision: Optional[str] = "0007_notifications"
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
        "organizations",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False, server_default="gym"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("branding", _json_type(), nullable=False, server_default=_json_object_default()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
        sa.CheckConstraint(
            "type IN ('gym', 'studio', 'coach', 'research', 'other')",
            name="ck_organizations_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_organizations_status",
        ),
    )

    op.create_table(
        "organization_memberships",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_organization_memberships_org_user",
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'trainer', 'member')",
            name="ck_organization_memberships_role",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_organization_memberships_status",
        ),
    )
    op.create_index(
        "ix_organization_memberships_org",
        "organization_memberships",
        ["organization_id"],
    )
    op.create_index(
        "ix_organization_memberships_user",
        "organization_memberships",
        ["user_id"],
    )

    op.create_table(
        "organization_invitations",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column(
            "invited_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint(
            "token_hash",
            name="uq_organization_invitations_token",
        ),
        sa.CheckConstraint(
            "role IN ('admin', 'trainer', 'member')",
            name="ck_organization_invitations_role",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'revoked', 'expired')",
            name="ck_organization_invitations_status",
        ),
    )
    op.create_index(
        "ix_organization_invitations_org",
        "organization_invitations",
        ["organization_id"],
    )
    op.create_index(
        "ix_organization_invitations_email",
        "organization_invitations",
        ["email"],
    )


def downgrade() -> None:
    op.drop_table("organization_invitations")
    op.drop_table("organization_memberships")
    op.drop_table("organizations")
