"""P0.3 workout execution, set logging, substitutions, and offline sync."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import (
    AppError,
    PlanNotFoundError,
    SetConflictError,
    SetNotFoundError,
    WorkoutCompletedError,
    WorkoutNotFoundError,
    WorkoutValidationError,
    validation_details,
)
from app.db.models import (
    ClientMutation,
    Plan,
    PlanDay,
    PlanVersion,
    Profile,
    SetLog,
    WorkoutExercise,
    WorkoutSession,
)
from app.domain.constants import BodyPart, Equipment, Focus
from app.domain.focus import is_exercise_focus
from app.domain.injuries import map_injury_to_body_parts
from app.schemas.recommendation import ErrorDetail
from app.schemas.workouts import (
    ExerciseSubstituteSyncPayload,
    SetCreateRequest,
    SetCreateSyncPayload,
    SetDeleteSyncPayload,
    SetOut,
    SetUpdateRequest,
    SetUpdateSyncPayload,
    SyncBatchResponse,
    SyncMutation,
    SyncMutationResult,
    WorkoutCompleteRequest,
    WorkoutCompleteSyncPayload,
    WorkoutExerciseOut,
    WorkoutResponse,
    WorkoutStartRequest,
    WorkoutSubstituteRequest,
    WorkoutSummary,
    WorkoutUpdateRequest,
)
from app.services.audit import record_audit
from app.services.dataset import Dataset
from app.services.identity import commit_or_conflict

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _duration_seconds(started_at: datetime, completed_at: datetime) -> int:
    return max(0, int((_as_utc(completed_at) - _as_utc(started_at)).total_seconds()))


def _profile_timezone(session: Session, user_id: uuid.UUID) -> str:
    profile = session.get(Profile, user_id)
    return profile.timezone if profile and profile.timezone else "UTC"


def _resolve_timezone(session: Session, user_id: uuid.UUID, requested: Optional[str]) -> str:
    candidate = requested or _profile_timezone(session, user_id)
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC"
    return candidate


def get_owned_workout(
    session: Session,
    *,
    workout_id: uuid.UUID,
    owner_user_id: uuid.UUID,
) -> WorkoutSession:
    workout = session.scalar(
        select(WorkoutSession)
        .options(
            selectinload(WorkoutSession.exercises).selectinload(WorkoutExercise.sets)
        )
        .where(
            WorkoutSession.id == workout_id,
            WorkoutSession.owner_user_id == owner_user_id,
            WorkoutSession.deleted_at.is_(None),
        )
    )
    if workout is None:
        raise WorkoutNotFoundError()
    return workout


def _load_plan_version(
    session: Session,
    *,
    plan: Plan,
    version_number: Optional[int],
) -> PlanVersion:
    target = version_number or plan.current_version
    version = session.scalar(
        select(PlanVersion).where(
            PlanVersion.plan_id == plan.id,
            PlanVersion.version == target,
        )
    )
    if version is None:
        raise WorkoutValidationError(
            "Versi plan tidak ditemukan.",
            details={"plan_id": str(plan.id), "version": target},
        )
    return version


def _load_plan_day(
    session: Session,
    *,
    version: PlanVersion,
    day_number: Optional[int],
) -> PlanDay:
    days = list(
        session.scalars(
            select(PlanDay)
            .options(selectinload(PlanDay.exercises))
            .where(PlanDay.plan_version_id == version.id)
            .order_by(PlanDay.day_number)
        ).all()
    )
    if not days:
        raise WorkoutValidationError("Plan tidak memiliki hari latihan.")
    if day_number is None:
        if len(days) != 1:
            raise WorkoutValidationError(
                "day wajib diisi untuk plan dengan lebih dari satu hari.",
                details={"available_days": [day.day_number for day in days]},
            )
        return days[0]
    for day in days:
        if day.day_number == day_number:
            return day
    raise WorkoutValidationError(
        "Hari plan tidak ditemukan.",
        details={"day": day_number},
    )


def start_workout(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    payload: WorkoutStartRequest,
    actor_role: str,
) -> WorkoutSession:
    if payload.client_session_id is not None:
        existing = session.scalar(
            select(WorkoutSession).where(
                WorkoutSession.owner_user_id == owner_user_id,
                WorkoutSession.client_session_id == payload.client_session_id,
                WorkoutSession.deleted_at.is_(None),
            )
        )
        if existing is not None:
            return get_owned_workout(
                session,
                workout_id=existing.id,
                owner_user_id=owner_user_id,
            )

    plan = session.scalar(
        select(Plan).where(
            Plan.id == payload.plan_id,
            Plan.owner_user_id == owner_user_id,
            Plan.deleted_at.is_(None),
        )
    )
    if plan is None:
        raise PlanNotFoundError()

    version = _load_plan_version(
        session,
        plan=plan,
        version_number=payload.plan_version,
    )
    day = _load_plan_day(
        session,
        version=version,
        day_number=payload.day,
    )

    snapshot = plan.input_snapshot or {}
    injuries = [str(item) for item in snapshot.get("injuries", [])]
    timezone_name = _resolve_timezone(session, owner_user_id, payload.timezone)

    workout = WorkoutSession(
        owner_user_id=owner_user_id,
        plan_id=plan.id,
        plan_version_id=version.id,
        plan_day_id=day.id,
        day_number=day.day_number,
        title=f"{plan.title} - Day {day.day_number}"[:160],
        focus=day.focus,
        status="in_progress",
        timezone=timezone_name,
        injuries=injuries,
        started_at=utcnow(),
        client_session_id=payload.client_session_id,
        exercise_count=len(day.exercises),
    )

    exercises: List[WorkoutExercise] = []
    for item in sorted(day.exercises, key=lambda exercise: exercise.position):
        exercises.append(
            WorkoutExercise(
                source_plan_exercise_id=item.id,
                exercise_id=item.exercise_id,
                exercise_name=item.exercise_name,
                body_part=item.body_part,
                equipment=list(item.equipment),
                primary_muscle=list(item.primary_muscle),
                secondary_muscle=list(item.secondary_muscle),
                image_url=item.image_url,
                position=item.position,
            )
        )
    workout.exercises = exercises
    session.add(workout)
    session.flush()

    record_audit(
        session,
        actor_user_id=owner_user_id,
        actor_role=actor_role,
        action="workout.started",
        resource_type="workout",
        resource_id=str(workout.id),
        metadata={
            "plan_id": str(plan.id),
            "plan_version": version.version,
            "day": day.day_number,
            "exercise_count": len(exercises),
        },
    )
    commit_or_conflict(session)
    return get_owned_workout(
        session,
        workout_id=workout.id,
        owner_user_id=owner_user_id,
    )


def serialize_set(set_log: SetLog) -> SetOut:
    return SetOut(
        id=set_log.id,
        workout_exercise_id=set_log.workout_exercise_id,
        set_number=set_log.set_number,
        reps=set_log.reps,
        weight_kg=float(set_log.weight_kg) if set_log.weight_kg is not None else None,
        rpe=float(set_log.rpe) if set_log.rpe is not None else None,
        completed=set_log.completed,
        notes=set_log.notes,
        client_set_id=set_log.client_set_id,
        created_at=set_log.created_at,
        updated_at=set_log.updated_at,
        deleted_at=set_log.deleted_at,
    )


def _exercise_out(exercise: WorkoutExercise) -> WorkoutExerciseOut:
    active_sets = [
        serialize_set(set_log)
        for set_log in sorted(exercise.sets, key=lambda item: item.set_number)
        if set_log.deleted_at is None
    ]
    return WorkoutExerciseOut(
        id=exercise.id,
        source_plan_exercise_id=exercise.source_plan_exercise_id,
        exercise_id=exercise.exercise_id,
        exercise_name=exercise.exercise_name,
        body_part=BodyPart(exercise.body_part),
        equipment=[Equipment(value) for value in exercise.equipment],
        primary_muscle=list(exercise.primary_muscle),
        secondary_muscle=list(exercise.secondary_muscle),
        exercise_image=exercise.image_url,
        position=exercise.position,
        notes=exercise.notes,
        substituted_from_exercise_id=exercise.substituted_from_exercise_id,
        sets=active_sets,
    )


def serialize_workout(workout: WorkoutSession) -> WorkoutResponse:
    return WorkoutResponse(
        id=workout.id,
        plan_id=workout.plan_id,
        plan_version_id=workout.plan_version_id,
        plan_day_id=workout.plan_day_id,
        day_number=workout.day_number,
        title=workout.title,
        focus=workout.focus,
        status=workout.status,
        timezone=workout.timezone,
        started_at=workout.started_at,
        completed_at=workout.completed_at,
        notes=workout.notes,
        client_session_id=workout.client_session_id,
        total_sets=workout.total_sets,
        total_reps=workout.total_reps,
        total_volume_kg=(
            float(workout.total_volume_kg) if workout.total_volume_kg is not None else 0
        ),
        exercise_count=workout.exercise_count,
        duration_seconds=workout.duration_seconds,
        exercises=[_exercise_out(exercise) for exercise in workout.exercises],
        created_at=workout.created_at,
        updated_at=workout.updated_at,
    )


def serialize_summary(workout: WorkoutSession) -> WorkoutSummary:
    return WorkoutSummary(
        id=workout.id,
        plan_id=workout.plan_id,
        day_number=workout.day_number,
        title=workout.title,
        focus=workout.focus,
        status=workout.status,
        timezone=workout.timezone,
        started_at=workout.started_at,
        completed_at=workout.completed_at,
        total_sets=workout.total_sets,
        total_reps=workout.total_reps,
        total_volume_kg=(
            float(workout.total_volume_kg) if workout.total_volume_kg is not None else 0
        ),
        exercise_count=workout.exercise_count,
        duration_seconds=workout.duration_seconds,
    )


def list_workouts(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    limit: int,
    cursor: Optional[str],
    status_filter: Optional[str] = None,
) -> Tuple[List[WorkoutSession], Optional[str]]:
    limit = min(max(limit, 1), 50)
    if status_filter is not None and status_filter not in {
        "in_progress",
        "completed",
        "abandoned",
    }:
        raise WorkoutValidationError(
            "Status workout tidak valid.",
            details={"status": status_filter},
        )

    stmt = (
        select(WorkoutSession)
        .where(
            WorkoutSession.owner_user_id == owner_user_id,
            WorkoutSession.deleted_at.is_(None),
        )
        .order_by(WorkoutSession.started_at.desc(), WorkoutSession.id.desc())
    )
    if status_filter:
        stmt = stmt.where(WorkoutSession.status == status_filter)

    if cursor:
        try:
            cursor_id = uuid.UUID(cursor)
        except ValueError as exc:
            raise WorkoutValidationError("Cursor workout tidak valid.") from exc
        cursor_workout = session.scalar(
            select(WorkoutSession).where(
                WorkoutSession.id == cursor_id,
                WorkoutSession.owner_user_id == owner_user_id,
                WorkoutSession.deleted_at.is_(None),
            )
        )
        if cursor_workout is None:
            raise WorkoutValidationError("Cursor workout tidak valid.")
        stmt = stmt.where(
            (WorkoutSession.started_at < cursor_workout.started_at)
            | (
                (WorkoutSession.started_at == cursor_workout.started_at)
                & (WorkoutSession.id < cursor_workout.id)
            )
        )

    workouts = list(session.scalars(stmt.limit(limit + 1)).all())
    next_cursor = str(workouts[limit - 1].id) if len(workouts) > limit else None
    return workouts[:limit], next_cursor


def update_workout(
    session: Session,
    *,
    workout: WorkoutSession,
    payload: WorkoutUpdateRequest,
    actor_role: str,
) -> WorkoutSession:
    if payload.notes is not None:
        workout.notes = payload.notes
        workout.updated_at = utcnow()
    record_audit(
        session,
        actor_user_id=workout.owner_user_id,
        actor_role=actor_role,
        action="workout.updated",
        resource_type="workout",
        resource_id=str(workout.id),
        metadata={"fields": ["notes"]},
    )
    commit_or_conflict(session)
    return workout


def _assert_editable(workout: WorkoutSession) -> None:
    if workout.status != "in_progress":
        raise WorkoutCompletedError()


def _find_workout_exercise(
    workout: WorkoutSession,
    workout_exercise_id: uuid.UUID,
) -> WorkoutExercise:
    for exercise in workout.exercises:
        if exercise.id == workout_exercise_id:
            return exercise
    raise WorkoutValidationError(
        "Exercise tidak ditemukan pada workout.",
        details={"workout_exercise_id": str(workout_exercise_id)},
    )


def _existing_client_set(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    client_set_id: uuid.UUID,
) -> Optional[SetLog]:
    return session.scalar(
        select(SetLog).where(
            SetLog.owner_user_id == owner_user_id,
            SetLog.client_set_id == client_set_id,
        )
    )


def _recalculate_totals(session: Session, workout: WorkoutSession) -> None:
    session.flush()
    rows = session.execute(
        select(SetLog.reps, SetLog.weight_kg)
        .join(WorkoutExercise, WorkoutExercise.id == SetLog.workout_exercise_id)
        .where(
            WorkoutExercise.workout_session_id == workout.id,
            SetLog.deleted_at.is_(None),
        )
    ).all()
    workout.total_sets = len(rows)
    workout.total_reps = sum(int(reps or 0) for reps, _ in rows)
    volume = sum(
        float(reps or 0) * float(weight or 0)
        for reps, weight in rows
    )
    workout.total_volume_kg = round(volume, 2)
    workout.exercise_count = len(workout.exercises)
    workout.updated_at = utcnow()


def _create_set(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    workout_id: uuid.UUID,
    payload: SetCreateRequest,
    actor_role: str,
) -> SetLog:
    workout = get_owned_workout(
        session,
        workout_id=workout_id,
        owner_user_id=owner_user_id,
    )
    _assert_editable(workout)

    client_set_id = payload.client_set_id or uuid.uuid4()
    existing = _existing_client_set(
        session,
        owner_user_id=owner_user_id,
        client_set_id=client_set_id,
    )
    if existing is not None:
        return existing

    exercise = _find_workout_exercise(workout, payload.workout_exercise_id)
    conflict = session.scalar(
        select(SetLog.id).where(
            SetLog.workout_exercise_id == exercise.id,
            SetLog.set_number == payload.set_number,
            SetLog.deleted_at.is_(None),
        )
    )
    if conflict is not None:
        raise SetConflictError(
            details={
                "workout_exercise_id": str(exercise.id),
                "set_number": payload.set_number,
            }
        )

    set_log = SetLog(
        workout_exercise_id=exercise.id,
        owner_user_id=owner_user_id,
        set_number=payload.set_number,
        reps=payload.reps,
        weight_kg=payload.weight_kg,
        rpe=payload.rpe,
        completed=payload.completed,
        notes=payload.notes,
        client_set_id=client_set_id,
    )
    session.add(set_log)
    session.flush()
    _recalculate_totals(session, workout)

    record_audit(
        session,
        actor_user_id=owner_user_id,
        actor_role=actor_role,
        action="workout.set_logged",
        resource_type="set_log",
        resource_id=str(set_log.id),
        metadata={
            "workout_id": str(workout.id),
            "set_number": payload.set_number,
            "completed": payload.completed,
        },
    )
    return set_log


def add_set(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    workout_id: uuid.UUID,
    payload: SetCreateRequest,
    actor_role: str,
) -> SetLog:
    set_log = _create_set(
        session,
        owner_user_id=owner_user_id,
        workout_id=workout_id,
        payload=payload,
        actor_role=actor_role,
    )
    commit_or_conflict(session)
    return set_log


def _get_owned_set(
    session: Session,
    *,
    set_id: uuid.UUID,
    owner_user_id: uuid.UUID,
) -> Tuple[SetLog, WorkoutSession]:
    set_log = session.get(SetLog, set_id)
    if set_log is None or set_log.owner_user_id != owner_user_id:
        raise SetNotFoundError()
    workout = set_log.exercise.session
    if workout.owner_user_id != owner_user_id or workout.deleted_at is not None:
        raise SetNotFoundError()
    return set_log, workout


def _update_set(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    set_id: uuid.UUID,
    payload: SetUpdateRequest,
    actor_role: str,
) -> SetLog:
    set_log, workout = _get_owned_set(
        session,
        set_id=set_id,
        owner_user_id=owner_user_id,
    )
    _assert_editable(workout)
    if set_log.deleted_at is not None:
        raise SetNotFoundError()

    data = payload.model_dump(exclude_unset=True)
    for field in ("reps", "weight_kg", "rpe", "completed", "notes"):
        if field in data:
            setattr(set_log, field, data[field])
    set_log.updated_at = utcnow()
    _recalculate_totals(session, workout)

    record_audit(
        session,
        actor_user_id=owner_user_id,
        actor_role=actor_role,
        action="workout.set_updated",
        resource_type="set_log",
        resource_id=str(set_log.id),
        metadata={"fields": sorted(data)},
    )
    return set_log


def update_set(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    set_id: uuid.UUID,
    payload: SetUpdateRequest,
    actor_role: str,
) -> SetLog:
    set_log = _update_set(
        session,
        owner_user_id=owner_user_id,
        set_id=set_id,
        payload=payload,
        actor_role=actor_role,
    )
    commit_or_conflict(session)
    return set_log


def _delete_set(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    set_id: uuid.UUID,
    actor_role: str,
) -> SetLog:
    set_log, workout = _get_owned_set(
        session,
        set_id=set_id,
        owner_user_id=owner_user_id,
    )
    _assert_editable(workout)
    if set_log.deleted_at is None:
        set_log.deleted_at = utcnow()
        set_log.updated_at = utcnow()
        _recalculate_totals(session, workout)
        record_audit(
            session,
            actor_user_id=owner_user_id,
            actor_role=actor_role,
            action="workout.set_deleted",
            resource_type="set_log",
            resource_id=str(set_log.id),
            metadata={"workout_id": str(workout.id)},
        )
    return set_log


def delete_set(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    set_id: uuid.UUID,
    actor_role: str,
) -> None:
    _delete_set(
        session,
        owner_user_id=owner_user_id,
        set_id=set_id,
        actor_role=actor_role,
    )
    commit_or_conflict(session)


def _complete_workout(
    session: Session,
    *,
    workout: WorkoutSession,
    payload: WorkoutCompleteRequest,
    actor_role: str,
) -> WorkoutSession:
    if workout.status == "completed":
        return workout
    _assert_editable(workout)

    completed_at = utcnow()
    workout.status = "completed"
    workout.completed_at = completed_at
    workout.duration_seconds = _duration_seconds(workout.started_at, completed_at)
    if payload.notes is not None:
        workout.notes = payload.notes
    _recalculate_totals(session, workout)

    record_audit(
        session,
        actor_user_id=workout.owner_user_id,
        actor_role=actor_role,
        action="workout.completed",
        resource_type="workout",
        resource_id=str(workout.id),
        metadata={
            "total_sets": workout.total_sets,
            "total_reps": workout.total_reps,
            "total_volume_kg": float(workout.total_volume_kg),
            "duration_seconds": workout.duration_seconds,
        },
    )
    return workout


def complete_workout(
    session: Session,
    *,
    workout: WorkoutSession,
    payload: WorkoutCompleteRequest,
    actor_role: str,
) -> WorkoutSession:
    completed = _complete_workout(
        session,
        workout=workout,
        payload=payload,
        actor_role=actor_role,
    )
    commit_or_conflict(session)
    return completed


def _substitute_exercise(
    session: Session,
    *,
    workout: WorkoutSession,
    workout_exercise_id: uuid.UUID,
    payload: WorkoutSubstituteRequest,
    dataset: Dataset,
    actor_role: str,
) -> WorkoutExercise:
    _assert_editable(workout)
    exercise = _find_workout_exercise(workout, workout_exercise_id)

    replacement = next(
        (
            item
            for item in dataset.exercises
            if item.exercise_id == payload.replacement_exercise_id
        ),
        None,
    )
    if replacement is None:
        raise WorkoutValidationError(
            "Exercise pengganti tidak ditemukan.",
            details={"exercise_id": payload.replacement_exercise_id},
        )
    if replacement.exercise_id == exercise.exercise_id:
        raise WorkoutValidationError("Exercise pengganti harus berbeda.")

    used_ids = {
        item.exercise_id
        for item in workout.exercises
        if item.id != exercise.id
    }
    if replacement.exercise_id in used_ids:
        raise WorkoutValidationError(
            "Exercise pengganti sudah dipakai di workout ini.",
            details={"exercise_id": replacement.exercise_id},
        )

    injured_parts = map_injury_to_body_parts(workout.injuries)
    if replacement.body_part in injured_parts:
        raise WorkoutValidationError(
            "Exercise pengganti berada pada area cedera.",
            details={"exercise_id": replacement.exercise_id},
        )
    if not is_exercise_focus(replacement.body_part, Focus(workout.focus)):
        raise WorkoutValidationError(
            "Exercise pengganti tidak sesuai fokus workout.",
            details={"exercise_id": replacement.exercise_id, "focus": workout.focus},
        )

    previous_exercise_id = exercise.exercise_id
    exercise.exercise_id = replacement.exercise_id
    exercise.exercise_name = replacement.exercise_name
    exercise.body_part = replacement.body_part.value
    exercise.equipment = [item.value for item in replacement.equipment]
    exercise.primary_muscle = list(replacement.primary_muscle)
    exercise.secondary_muscle = list(replacement.secondary_muscle)
    exercise.image_url = replacement.image_url
    exercise.substituted_from_exercise_id = (
        exercise.substituted_from_exercise_id or previous_exercise_id
    )

    record_audit(
        session,
        actor_user_id=workout.owner_user_id,
        actor_role=actor_role,
        action="workout.exercise_substituted",
        resource_type="workout_exercise",
        resource_id=str(exercise.id),
        metadata={
            "workout_id": str(workout.id),
            "from_exercise_id": previous_exercise_id,
            "to_exercise_id": replacement.exercise_id,
        },
    )
    return exercise


def substitute_exercise(
    session: Session,
    *,
    workout: WorkoutSession,
    workout_exercise_id: uuid.UUID,
    payload: WorkoutSubstituteRequest,
    dataset: Dataset,
    actor_role: str,
) -> WorkoutExercise:
    exercise = _substitute_exercise(
        session,
        workout=workout,
        workout_exercise_id=workout_exercise_id,
        payload=payload,
        dataset=dataset,
        actor_role=actor_role,
    )
    commit_or_conflict(session)
    return exercise


def _sync_error(
    client_mutation_id: str,
    code: str,
    message: str,
    details: Any = None,
) -> SyncMutationResult:
    return SyncMutationResult(
        client_mutation_id=client_mutation_id,
        status="error",
        error=ErrorDetail(code=code, message=message, details=details),
    )


def _dispatch_mutation(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    mutation: SyncMutation,
    dataset: Dataset,
    actor_role: str,
) -> Dict[str, Any]:
    if mutation.type == "set.create":
        create_payload = SetCreateSyncPayload.model_validate(mutation.payload)
        set_log = _create_set(
            session,
            owner_user_id=owner_user_id,
            workout_id=create_payload.workout_id,
            payload=create_payload,
            actor_role=actor_role,
        )
        return {
            "workout_id": str(create_payload.workout_id),
            "set_id": str(set_log.id),
            "set_number": set_log.set_number,
        }

    if mutation.type == "set.update":
        update_payload = SetUpdateSyncPayload.model_validate(mutation.payload)
        set_log = _update_set(
            session,
            owner_user_id=owner_user_id,
            set_id=update_payload.set_id,
            payload=update_payload,
            actor_role=actor_role,
        )
        return {"set_id": str(set_log.id), "status": "updated"}

    if mutation.type == "set.delete":
        delete_payload = SetDeleteSyncPayload.model_validate(mutation.payload)
        set_log = _delete_set(
            session,
            owner_user_id=owner_user_id,
            set_id=delete_payload.set_id,
            actor_role=actor_role,
        )
        return {"set_id": str(set_log.id), "status": "deleted"}

    if mutation.type == "workout.complete":
        complete_payload = WorkoutCompleteSyncPayload.model_validate(mutation.payload)
        workout = get_owned_workout(
            session,
            workout_id=complete_payload.workout_id,
            owner_user_id=owner_user_id,
        )
        completed = _complete_workout(
            session,
            workout=workout,
            payload=WorkoutCompleteRequest(notes=complete_payload.notes),
            actor_role=actor_role,
        )
        return {
            "workout_id": str(completed.id),
            "status": completed.status,
            "total_sets": completed.total_sets,
            "total_reps": completed.total_reps,
            "total_volume_kg": float(completed.total_volume_kg),
        }

    if mutation.type == "exercise.substitute":
        substitute_payload = ExerciseSubstituteSyncPayload.model_validate(mutation.payload)
        workout = get_owned_workout(
            session,
            workout_id=substitute_payload.workout_id,
            owner_user_id=owner_user_id,
        )
        exercise = _substitute_exercise(
            session,
            workout=workout,
            workout_exercise_id=substitute_payload.workout_exercise_id,
            payload=WorkoutSubstituteRequest(
                replacement_exercise_id=substitute_payload.replacement_exercise_id
            ),
            dataset=dataset,
            actor_role=actor_role,
        )
        return {
            "workout_exercise_id": str(exercise.id),
            "exercise_id": exercise.exercise_id,
        }

    raise WorkoutValidationError(
        "Tipe mutation tidak didukung.",
        details={"type": mutation.type},
    )


def apply_sync_batch(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    mutations: Sequence[SyncMutation],
    dataset: Dataset,
    actor_role: str,
) -> SyncBatchResponse:
    results: List[SyncMutationResult] = []

    for mutation in mutations:
        existing = session.scalar(
            select(ClientMutation).where(
                ClientMutation.owner_user_id == owner_user_id,
                ClientMutation.client_mutation_id == mutation.client_mutation_id,
            )
        )
        if existing is not None:
            results.append(
                SyncMutationResult(
                    client_mutation_id=mutation.client_mutation_id,
                    status="duplicate",
                    result=dict(existing.result or {}),
                )
            )
            continue

        try:
            with session.begin_nested():
                payload = _dispatch_mutation(
                    session,
                    owner_user_id=owner_user_id,
                    mutation=mutation,
                    dataset=dataset,
                    actor_role=actor_role,
                )
                session.add(
                    ClientMutation(
                        owner_user_id=owner_user_id,
                        client_mutation_id=mutation.client_mutation_id,
                        mutation_type=mutation.type,
                        result=payload,
                        occurred_at=mutation.occurred_at,
                    )
                )
                session.flush()
            results.append(
                SyncMutationResult(
                    client_mutation_id=mutation.client_mutation_id,
                    status="applied",
                    result=payload,
                )
            )
        except AppError as exc:
            results.append(
                _sync_error(
                    mutation.client_mutation_id,
                    exc.code,
                    exc.message,
                    exc.details,
                )
            )
        except ValidationError as exc:
            results.append(
                _sync_error(
                    mutation.client_mutation_id,
                    "validation_error",
                    "Payload mutation tidak valid.",
                    validation_details([dict(item) for item in exc.errors()]),
                )
            )
        except Exception:
            logger.exception(
                "sync_mutation_failed",
                extra={
                    "owner_user_id": str(owner_user_id),
                    "client_mutation_id": mutation.client_mutation_id,
                    "mutation_type": mutation.type,
                },
            )
            results.append(
                _sync_error(
                    mutation.client_mutation_id,
                    "internal_error",
                    "Mutation gagal diterapkan.",
                )
            )

    commit_or_conflict(session)
    return SyncBatchResponse(results=results)
