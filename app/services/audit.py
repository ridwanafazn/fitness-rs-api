"""Append-only audit helpers.

Audit metadata must never contain health terms, notes, email addresses, or
tokens.  Callers pass only counts, field names, and enum values.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db.models import AuditLog


def record_audit(
    session: Session,
    *,
    actor_user_id: Optional[uuid.UUID],
    actor_role: Optional[str],
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    entry = AuditLog(
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata_json=metadata or {},
    )
    session.add(entry)
    return entry


def actor_role_label(roles: list[str]) -> str:
    """Stable, compact role label for an audit row."""

    if not roles:
        return "user"
    return ",".join(sorted(dict.fromkeys(roles)))
