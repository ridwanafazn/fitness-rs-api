"""SQLAlchemy models for P0.1 identity, profiles, consent, and audit."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp used as a Python-side default."""

    return datetime.now(UTC)


def json_type():
    """JSONB on Postgres, portable JSON everywhere else (tests, local SQLite)."""

    return JSON().with_variant(postgresql.JSONB, "postgresql")


def text_array_type():
    """text[] on Postgres, JSON on SQLite for local development and tests."""

    return postgresql.ARRAY(Text()).with_variant(JSON, "sqlite")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("auth_issuer", "auth_subject", name="uq_users_auth_identity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    auth_issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(320))
    display_name: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    deletion_requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deletion_scheduled_for: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    profile: Mapped[Optional[Profile]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    equipment: Mapped[List[UserEquipment]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    injuries: Mapped[List[UserInjury]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    consents: Mapped[List[Consent]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    roles: Mapped[List[UserRole]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="UserRole.user_id",
    )


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint("gender IN ('male', 'female')", name="ck_profiles_gender"),
        CheckConstraint(
            "goal IN ('muscle_gain', 'fat_loss', 'general_health')",
            name="ck_profiles_goal",
        ),
        CheckConstraint(
            "experience IN ('beginner', 'intermediate', 'advanced')",
            name="ck_profiles_experience",
        ),
        CheckConstraint(
            "session_minutes IN (30, 45, 60, 90)",
            name="ck_profiles_session_minutes",
        ),
        CheckConstraint(
            "unit_system IN ('metric', 'imperial')",
            name="ck_profiles_unit_system",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    gender: Mapped[Optional[str]] = mapped_column(String(16))
    height_cm: Mapped[Optional[float]] = mapped_column(Numeric(5, 2))
    weight_kg: Mapped[Optional[float]] = mapped_column(Numeric(5, 2))
    goal: Mapped[Optional[str]] = mapped_column(String(32))
    experience: Mapped[Optional[str]] = mapped_column(String(16))
    session_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    timezone: Mapped[Optional[str]] = mapped_column(String(64))
    locale: Mapped[Optional[str]] = mapped_column(String(16))
    unit_system: Mapped[Optional[str]] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="profile")


class UserEquipment(Base):
    __tablename__ = "user_equipment"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    equipment: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="equipment")


class UserInjury(Base):
    __tablename__ = "user_injuries"
    __table_args__ = (
        UniqueConstraint("user_id", "term", name="uq_user_injuries_user_term"),
        Index("ix_user_injuries_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    term: Mapped[str] = mapped_column(String(60), nullable=False)
    body_parts: Mapped[List[str]] = mapped_column(text_array_type(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="injuries")


class Consent(Base):
    __tablename__ = "consents"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('health_data_processing', 'research_analytics', "
            "'trainer_sharing', 'marketing')",
            name="ck_consents_kind",
        ),
        Index("ix_consents_user_kind_granted", "user_id", "kind", "granted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ip_hash: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="consents")


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'trainer', 'org_admin', 'platform_admin')",
            name="ck_user_roles_role",
        ),
        UniqueConstraint("user_id", "role", "org_id", name="uq_user_roles_user_role_org"),
        Index(
            "uq_user_roles_user_role_platform",
            "user_id",
            "role",
            unique=True,
            postgresql_where=text("org_id IS NULL"),
            sqlite_where=text("org_id IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    granted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    user: Mapped[User] = relationship(back_populates="roles", foreign_keys=[user_id])


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_actor_created", "actor_user_id", "created_at"),
        Index("ix_audit_log_resource", "resource_type", "resource_id"),
        Index("ix_audit_log_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    actor_role: Mapped[Optional[str]] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(50))
    resource_id: Mapped[Optional[str]] = mapped_column(String(64))
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(
        "metadata",
        json_type(),
        default=dict,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived', 'deleted')",
            name="ck_plans_status",
        ),
        Index("ix_plans_owner_created", "owner_user_id", "created_at"),
        Index(
            "uq_plans_owner_idempotency",
            "owner_user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
            sqlite_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    input_snapshot: Mapped[Dict[str, Any]] = mapped_column(json_type(), nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    split_type: Mapped[str] = mapped_column(String(32), nullable=False)
    day_count: Mapped[int] = mapped_column(Integer, nullable=False)
    bmi: Mapped[Optional[float]] = mapped_column(Numeric(5, 2))
    bmi_category: Mapped[Optional[str]] = mapped_column(String(32))
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128))
    idempotency_hash: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    versions: Mapped[List[PlanVersion]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
    )
    shares: Mapped[List[PlanShare]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
    )


class PlanVersion(Base):
    __tablename__ = "plan_versions"
    __table_args__ = (
        UniqueConstraint("plan_id", "version", name="uq_plan_versions_plan_version"),
        Index("ix_plan_versions_plan_id", "plan_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    split_type: Mapped[str] = mapped_column(String(32), nullable=False)
    schedule: Mapped[Dict[str, str]] = mapped_column(json_type(), nullable=False)
    warnings: Mapped[List[str]] = mapped_column(json_type(), default=list, nullable=False)
    day_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    plan: Mapped[Plan] = relationship(back_populates="versions")
    days: Mapped[List[PlanDay]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
        order_by="PlanDay.day_number",
    )


class PlanDay(Base):
    __tablename__ = "plan_days"
    __table_args__ = (
        UniqueConstraint("plan_version_id", "day_number", name="uq_plan_days_version_day"),
        CheckConstraint("day_number > 0", name="ck_plan_days_day_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("plan_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    day_number: Mapped[int] = mapped_column(Integer, nullable=False)
    focus: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    version: Mapped[PlanVersion] = relationship(back_populates="days")
    exercises: Mapped[List[PlanExercise]] = relationship(
        back_populates="day",
        cascade="all, delete-orphan",
        order_by="PlanExercise.position",
    )


class PlanExercise(Base):
    __tablename__ = "plan_exercises"
    __table_args__ = (
        UniqueConstraint("plan_day_id", "position", name="uq_plan_exercises_day_position"),
        CheckConstraint("position >= 0", name="ck_plan_exercises_position"),
        Index("ix_plan_exercises_day_id", "plan_day_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_day_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("plan_days.id", ondelete="CASCADE"),
        nullable=False,
    )
    exercise_id: Mapped[str] = mapped_column(String(64), nullable=False)
    exercise_name: Mapped[str] = mapped_column(String(255), nullable=False)
    body_part: Mapped[str] = mapped_column(String(32), nullable=False)
    equipment: Mapped[List[str]] = mapped_column(json_type(), nullable=False)
    primary_muscle: Mapped[List[str]] = mapped_column(json_type(), nullable=False)
    secondary_muscle: Mapped[List[str]] = mapped_column(json_type(), default=list, nullable=False)
    image_url: Mapped[Optional[str]] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    day: Mapped[PlanDay] = relationship(back_populates="exercises")


class PlanShare(Base):
    __tablename__ = "plan_shares"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_plan_shares_token_hash"),
        Index("ix_plan_shares_plan_expires", "plan_id", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    plan: Mapped[Plan] = relationship(back_populates="shares")
