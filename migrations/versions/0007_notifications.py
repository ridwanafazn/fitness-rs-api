"""P1.3 notification preferences, devices, outbox, and integrations.

Revision ID: 0007_notifications
Revises: 0006_trainer
Create Date: 2026-11-23
"""

from __future__ import annotations

from typing import Optional

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_notifications"
down_revision: Optional[str] = "0006_trainer"
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
        "notification_preferences",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("push_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("whatsapp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reminder_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reminder_time", sa.String(length=5), nullable=False, server_default="18:00"),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("quiet_hours_start", sa.String(length=5), nullable=True),
        sa.Column("quiet_hours_end", sa.String(length=5), nullable=True),
        sa.Column("weekly_review_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("calendar_token_hash", sa.String(length=64), nullable=True),
        sa.Column("calendar_token_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint(
            "owner_user_id",
            name="uq_notification_preferences_owner",
        ),
        sa.UniqueConstraint(
            "calendar_token_hash",
            name="uq_notification_preferences_calendar_token",
        ),
    )

    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("device_name", sa.String(length=120), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_ciphertext", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint("owner_user_id", "token_hash", name="uq_devices_owner_token"),
    )
    op.create_index("ix_devices_owner", "devices", ["owner_user_id"])

    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("template", sa.String(length=64), nullable=False),
        sa.Column("payload", _json_type(), nullable=False, server_default=_json_object_default()),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint("idempotency_key", name="uq_notification_outbox_key"),
        sa.CheckConstraint(
            "channel IN ('email', 'push', 'whatsapp')",
            name="ck_notification_outbox_channel",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'cancelled')",
            name="ck_notification_outbox_status",
        ),
    )
    op.create_index(
        "ix_notification_outbox_due",
        "notification_outbox",
        ["status", "scheduled_at"],
    )
    op.create_index(
        "ix_notification_outbox_owner",
        "notification_outbox",
        ["owner_user_id", "created_at"],
    )

    op.create_table(
        "integration_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_user_id", sa.String(length=128), nullable=True),
        sa.Column("access_token_ciphertext", sa.Text(), nullable=True),
        sa.Column("refresh_token_ciphertext", sa.Text(), nullable=True),
        sa.Column("scopes", _json_type(), nullable=False, server_default=_json_list_default()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint(
            "owner_user_id",
            "provider",
            name="uq_integration_tokens_owner_provider",
        ),
        sa.CheckConstraint(
            "provider IN ('strava', 'google_fit', 'apple_health')",
            name="ck_integration_tokens_provider",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_integration_tokens_status",
        ),
    )
    op.create_index(
        "ix_integration_tokens_owner",
        "integration_tokens",
        ["owner_user_id"],
    )


def downgrade() -> None:
    op.drop_table("integration_tokens")
    op.drop_table("notification_outbox")
    op.drop_table("devices")
    op.drop_table("notification_preferences")
