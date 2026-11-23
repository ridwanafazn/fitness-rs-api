"""SQLAlchemy models for P0.1 identity, profiles, consent, and audit."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
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

class WorkoutSession(Base):
    __tablename__ = "workout_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress', 'completed', 'abandoned')",
            name="ck_workout_sessions_status",
        ),
        Index(
            "ix_workout_sessions_owner_started",
            "owner_user_id",
            "started_at",
        ),
        Index(
            "uq_workout_sessions_owner_client",
            "owner_user_id",
            "client_session_id",
            unique=True,
            postgresql_where=text("client_session_id IS NOT NULL"),
            sqlite_where=text("client_session_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("plans.id", ondelete="SET NULL"),
    )
    plan_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("plan_versions.id", ondelete="SET NULL"),
    )
    plan_day_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("plan_days.id", ondelete="SET NULL"),
    )
    day_number: Mapped[Optional[int]] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    focus: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="in_progress", nullable=False
    )
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    injuries: Mapped[List[str]] = mapped_column(json_type(), default=list, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    client_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    total_sets: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_reps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_volume_kg: Mapped[float] = mapped_column(
        Numeric(10, 2), default=0, nullable=False
    )
    exercise_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    exercises: Mapped[List[WorkoutExercise]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="WorkoutExercise.position",
    )


class WorkoutExercise(Base):
    __tablename__ = "workout_exercises"
    __table_args__ = (
        UniqueConstraint(
            "workout_session_id",
            "position",
            name="uq_workout_exercises_session_position",
        ),
        Index("ix_workout_exercises_session", "workout_session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workout_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("workout_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_plan_exercise_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("plan_exercises.id", ondelete="SET NULL"),
    )
    exercise_id: Mapped[str] = mapped_column(String(64), nullable=False)
    exercise_name: Mapped[str] = mapped_column(String(255), nullable=False)
    body_part: Mapped[str] = mapped_column(String(32), nullable=False)
    equipment: Mapped[List[str]] = mapped_column(json_type(), nullable=False)
    primary_muscle: Mapped[List[str]] = mapped_column(json_type(), nullable=False)
    secondary_muscle: Mapped[List[str]] = mapped_column(
        json_type(), default=list, nullable=False
    )
    image_url: Mapped[Optional[str]] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    substituted_from_exercise_id: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    session: Mapped[WorkoutSession] = relationship(back_populates="exercises")
    sets: Mapped[List[SetLog]] = relationship(
        back_populates="exercise",
        cascade="all, delete-orphan",
        order_by="SetLog.set_number",
    )


class SetLog(Base):
    __tablename__ = "set_logs"
    __table_args__ = (
        Index(
            "uq_set_logs_owner_client",
            "owner_user_id",
            "client_set_id",
            unique=True,
            postgresql_where=text("client_set_id IS NOT NULL"),
            sqlite_where=text("client_set_id IS NOT NULL"),
        ),
        Index(
            "uq_set_logs_exercise_set",
            "workout_exercise_id",
            "set_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_set_logs_workout_exercise", "workout_exercise_id"),
        CheckConstraint("set_number >= 1", name="ck_set_logs_set_number"),
        CheckConstraint(
            "reps IS NULL OR reps >= 0",
            name="ck_set_logs_reps",
        ),
        CheckConstraint(
            "weight_kg IS NULL OR weight_kg >= 0",
            name="ck_set_logs_weight",
        ),
        CheckConstraint(
            "rpe IS NULL OR (rpe >= 1 AND rpe <= 10)",
            name="ck_set_logs_rpe",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workout_exercise_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("workout_exercises.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reps: Mapped[Optional[int]] = mapped_column(Integer)
    weight_kg: Mapped[Optional[float]] = mapped_column(Numeric(7, 2))
    rpe: Mapped[Optional[float]] = mapped_column(Numeric(3, 1))
    completed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    client_set_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    exercise: Mapped[WorkoutExercise] = relationship(back_populates="sets")


class ClientMutation(Base):
    __tablename__ = "client_mutations"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "client_mutation_id",
            name="uq_client_mutations_owner_client",
        ),
        Index("ix_client_mutations_owner", "owner_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_mutation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mutation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[Dict[str, Any]] = mapped_column(
        json_type(), default=dict, nullable=False
    )
    occurred_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint(
            "rating IS NULL OR (rating >= 1 AND rating <= 5)",
            name="ck_feedback_rating",
        ),
        CheckConstraint(
            "difficulty IS NULL OR difficulty IN ('too_easy', 'just_right', 'too_hard')",
            name="ck_feedback_difficulty",
        ),
        Index("ix_feedback_owner_created", "owner_user_id", "created_at"),
        Index("ix_feedback_plan", "plan_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("plans.id", ondelete="SET NULL"),
    )
    plan_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("plan_versions.id", ondelete="SET NULL"),
    )
    workout_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("workout_sessions.id", ondelete="SET NULL"),
    )
    rating: Mapped[Optional[int]] = mapped_column(Integer)
    difficulty: Mapped[Optional[str]] = mapped_column(String(16))
    pain: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pain_area: Mapped[Optional[str]] = mapped_column(String(60))
    comment: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class UnsafeReport(Base):
    __tablename__ = "unsafe_reports"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_unsafe_reports_severity",
        ),
        CheckConstraint(
            "status IN ('open', 'triaged', 'resolved', 'dismissed')",
            name="ck_unsafe_reports_status",
        ),
        Index("ix_unsafe_reports_status_created", "status", "created_at"),
        Index("ix_unsafe_reports_severity", "severity"),
        Index("ix_unsafe_reports_reporter_created", "reporter_user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    reporter_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    plan_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("plans.id", ondelete="SET NULL"),
    )
    plan_exercise_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("plan_exercises.id", ondelete="SET NULL"),
    )
    workout_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("workout_sessions.id", ondelete="SET NULL"),
    )
    exercise_id: Mapped[str] = mapped_column(String(64), nullable=False)
    exercise_name: Mapped[Optional[str]] = mapped_column(String(255))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(16), default="medium", nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    resolution_note: Mapped[Optional[str]] = mapped_column(Text)
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    triaged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

class DailyMetric(Base):
    __tablename__ = "daily_metrics"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "metric_date",
            name="uq_daily_metrics_owner_date",
        ),
        Index("ix_daily_metrics_owner_date", "owner_user_id", "metric_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    workouts_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_sets: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_reps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_volume_kg: Mapped[float] = mapped_column(
        Numeric(12, 2), default=0, nullable=False
    )
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sets_by_body_part: Mapped[Dict[str, int]] = mapped_column(
        json_type(), default=dict, nullable=False
    )
    volume_by_body_part: Mapped[Dict[str, float]] = mapped_column(
        json_type(), default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class PersonalRecord(Base):
    __tablename__ = "personal_records"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "exercise_id",
            "record_type",
            name="uq_personal_records_owner_exercise_type",
        ),
        Index("ix_personal_records_owner", "owner_user_id"),
        CheckConstraint(
            "record_type IN ('max_weight', 'max_reps', 'max_volume')",
            name="ck_personal_records_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    exercise_id: Mapped[str] = mapped_column(String(64), nullable=False)
    exercise_name: Mapped[str] = mapped_column(String(255), nullable=False)
    record_type: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    reps: Mapped[Optional[int]] = mapped_column(Integer)
    weight_kg: Mapped[Optional[float]] = mapped_column(Numeric(7, 2))
    achieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    set_log_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("set_logs.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class WeeklyReview(Base):
    __tablename__ = "weekly_reviews"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "week_start",
            name="uq_weekly_reviews_owner_week",
        ),
        Index("ix_weekly_reviews_owner_week", "owner_user_id", "week_start"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    workouts_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_sets: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_reps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_volume_kg: Mapped[float] = mapped_column(
        Numeric(12, 2), default=0, nullable=False
    )
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sets_by_body_part: Mapped[Dict[str, int]] = mapped_column(
        json_type(), default=dict, nullable=False
    )
    volume_by_body_part: Mapped[Dict[str, float]] = mapped_column(
        json_type(), default=dict, nullable=False
    )
    summary: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

class TrainerProfile(Base):
    __tablename__ = "trainer_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_trainer_profiles_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    bio: Mapped[Optional[str]] = mapped_column(Text)
    specialties: Mapped[List[str]] = mapped_column(
        json_type(), default=list, nullable=False
    )
    years_experience: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class TrainerClient(Base):
    __tablename__ = "trainer_clients"
    __table_args__ = (
        UniqueConstraint(
            "trainer_user_id",
            "client_user_id",
            name="uq_trainer_clients_pair",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_trainer_clients_status",
        ),
        Index("ix_trainer_clients_trainer", "trainer_user_id"),
        Index("ix_trainer_clients_client", "client_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    trainer_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class TrainerInvitation(Base):
    __tablename__ = "trainer_invitations"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_trainer_invitations_token"),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'revoked', 'expired')",
            name="ck_trainer_invitations_status",
        ),
        Index("ix_trainer_invitations_trainer", "trainer_user_id"),
        Index("ix_trainer_invitations_email", "client_email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    trainer_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    client_email: Mapped[str] = mapped_column(String(320), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_scopes: Mapped[List[str]] = mapped_column(
        json_type(), default=list, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    declined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class AccessGrant(Base):
    __tablename__ = "access_grants"
    __table_args__ = (
        UniqueConstraint(
            "trainer_client_id",
            "scope",
            name="uq_access_grants_client_scope",
        ),
        CheckConstraint(
            "scope IN ('plans', 'workouts', 'feedback', 'progress')",
            name="ck_access_grants_scope",
        ),
        Index("ix_access_grants_client", "trainer_client_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    trainer_client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("trainer_clients.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class PlanReview(Base):
    __tablename__ = "plan_reviews"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "trainer_user_id",
            name="uq_plan_reviews_plan_trainer",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'changes_requested')",
            name="ck_plan_reviews_status",
        ),
        Index("ix_plan_reviews_plan", "plan_id"),
        Index("ix_plan_reviews_trainer", "trainer_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("plan_versions.id", ondelete="SET NULL"),
    )
    trainer_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16), default="pending", nullable=False
    )
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class TrainerComment(Base):
    __tablename__ = "trainer_comments"
    __table_args__ = (
        Index("ix_trainer_comments_client_created", "client_user_id", "created_at"),
        Index("ix_trainer_comments_trainer_created", "trainer_user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    trainer_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("plans.id", ondelete="SET NULL"),
    )
    workout_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("workout_sessions.id", ondelete="SET NULL"),
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("owner_user_id", name="uq_notification_preferences_owner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reminder_time: Mapped[str] = mapped_column(String(5), default="18:00", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    quiet_hours_start: Mapped[Optional[str]] = mapped_column(String(5))
    quiet_hours_end: Mapped[Optional[str]] = mapped_column(String(5))
    weekly_review_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    calendar_token_hash: Mapped[Optional[str]] = mapped_column(String(64))
    calendar_token_created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "token_hash", name="uq_devices_owner_token"),
        Index("ix_devices_owner", "owner_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    device_name: Mapped[Optional[str]] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_ciphertext: Mapped[Optional[str]] = mapped_column(Text)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_notification_outbox_key"),
        CheckConstraint(
            "channel IN ('email', 'push', 'whatsapp')",
            name="ck_notification_outbox_channel",
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'cancelled')",
            name="ck_notification_outbox_status",
        ),
        Index("ix_notification_outbox_due", "status", "scheduled_at"),
        Index("ix_notification_outbox_owner", "owner_user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(
        json_type(), default=dict, nullable=False
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IntegrationToken(Base):
    __tablename__ = "integration_tokens"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "provider", name="uq_integration_tokens_owner_provider"),
        CheckConstraint(
            "provider IN ('strava', 'google_fit', 'apple_health')",
            name="ck_integration_tokens_provider",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_integration_tokens_status",
        ),
        Index("ix_integration_tokens_owner", "owner_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_user_id: Mapped[Optional[str]] = mapped_column(String(128))
    access_token_ciphertext: Mapped[Optional[str]] = mapped_column(Text)
    refresh_token_ciphertext: Mapped[Optional[str]] = mapped_column(Text)
    scopes: Mapped[List[str]] = mapped_column(json_type(), default=list, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_organizations_slug"),
        CheckConstraint(
            "type IN ('gym', 'studio', 'coach', 'research', 'other')",
            name="ck_organizations_type",
        ),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_organizations_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(16), default="gym", nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    website: Mapped[Optional[str]] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    branding: Mapped[Dict[str, Any]] = mapped_column(
        json_type(), default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class OrganizationMembership(Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_organization_memberships_org_user",
        ),
        CheckConstraint(
            "role IN ('owner', 'admin', 'trainer', 'member')",
            name="ck_organization_memberships_role",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_organization_memberships_status",
        ),
        Index("ix_organization_memberships_org", "organization_id"),
        Index("ix_organization_memberships_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class OrganizationInvitation(Base):
    __tablename__ = "organization_invitations"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_organization_invitations_token"),
        CheckConstraint(
            "role IN ('admin', 'trainer', 'member')",
            name="ck_organization_invitations_role",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'revoked', 'expired')",
            name="ck_organization_invitations_status",
        ),
        Index("ix_organization_invitations_org", "organization_id"),
        Index("ix_organization_invitations_email", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    invited_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    declined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class ResearchEvent(Base):
    __tablename__ = "research_events"
    __table_args__ = (
        Index(
            "uq_research_events_owner_idempotency",
            "owner_user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
            sqlite_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_research_events_owner_occurred", "owner_user_id", "occurred_at"),
        Index("ix_research_events_name_occurred", "name", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    properties: Mapped[Dict[str, Any]] = mapped_column(
        json_type(), default=dict, nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (
        UniqueConstraint("key", name="uq_experiments_key"),
        CheckConstraint(
            "status IN ('draft', 'running', 'paused', 'completed')",
            name="ck_experiments_status",
        ),
        CheckConstraint(
            "traffic_percent >= 0 AND traffic_percent <= 100",
            name="ck_experiments_traffic",
        ),
        Index("ix_experiments_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    variants: Mapped[List[Dict[str, Any]]] = mapped_column(
        json_type(), default=list, nullable=False
    )
    traffic_percent: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class ExperimentAssignment(Base):
    __tablename__ = "experiment_assignments"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id",
            "user_id",
            name="uq_experiment_assignments_experiment_user",
        ),
        Index("ix_experiment_assignments_user", "user_id"),
        Index(
            "ix_experiment_assignments_experiment_variant",
            "experiment_id",
            "variant",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    variant: Mapped[str] = mapped_column(String(64), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    exposed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ResearchVersion(Base):
    __tablename__ = "research_versions"
    __table_args__ = (
        UniqueConstraint("kind", "version", name="uq_research_versions_kind_version"),
        CheckConstraint(
            "kind IN ('dataset', 'algorithm')",
            name="ck_research_versions_kind",
        ),
        Index("ix_research_versions_kind_created", "kind", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[Optional[int]] = mapped_column(Integer)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(
        json_type(), default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class QualityReview(Base):
    __tablename__ = "quality_reviews"
    __table_args__ = (
        CheckConstraint(
            "subject_type IN ('plan_version', 'dataset_version', 'algorithm_version')",
            name="ck_quality_reviews_subject_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'in_review', 'approved', 'changes_requested')",
            name="ck_quality_reviews_status",
        ),
        Index("ix_quality_reviews_subject", "subject_type", "subject_id"),
        Index("ix_quality_reviews_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    reviewer_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    subject_type: Mapped[str] = mapped_column(String(24), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    rubric: Mapped[Dict[str, Any]] = mapped_column(
        json_type(), default=dict, nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
