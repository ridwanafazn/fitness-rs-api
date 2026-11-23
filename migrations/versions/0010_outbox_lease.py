"""P2.3 outbox worker lease for multi-worker safety.

Revision ID: 0010_outbox_lease
Revises: 0009_research
Create Date: 2026-11-23
"""

from __future__ import annotations

from typing import Optional

import sqlalchemy as sa
from alembic import op

revision = "0010_outbox_lease"
down_revision: Optional[str] = "0009_research"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("notification_outbox") as batch_op:
        batch_op.add_column(
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("locked_by", sa.String(length=64), nullable=True)
        )
    op.create_index(
        "ix_notification_outbox_lease",
        "notification_outbox",
        ["status", "scheduled_at", "locked_until"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_outbox_lease",
        table_name="notification_outbox",
    )
    with op.batch_alter_table("notification_outbox") as batch_op:
        batch_op.drop_column("locked_by")
        batch_op.drop_column("locked_until")
