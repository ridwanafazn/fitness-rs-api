"""P0.2 plan lifecycle: persistence, versions, edits, sharing, and export."""

from __future__ import annotations

import hashlib
import io
import json
import random
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.errors import (
    ConflictError,
    ExerciseLockedError,
    IdempotencyConflictError,
    InsufficientPoolError,
    InvalidCursorError,
    PlanDatasetMismatchError,
    PlanNotFoundError,
    PlanRevisionConflictError,
    PlanValidationError,
    PreconditionRequiredError,
    ShareNotFoundError,
)
from app.db.models import Plan, PlanDay, PlanExercise, PlanShare, PlanVersion
from app.domain.constants import BodyPart, Equipment, Focus
from app.domain.focus import is_exercise_focus, num_exercises_for_focus
from app.domain.injuries import map_injury_to_body_parts
from app.domain.models import Exercise, UserProfile
from app.schemas.plans import (
    PlanDayOut,
    PlanExerciseOut,
    PlanResponse,
    PlanShareResponse,
    PlanSummary,
    PlanUpdateRequest,
    PlanVersionOut,
    PublicPlanResponse,
)
from app.schemas.recommendation import RecommendationRequest, RecommendationResponse
from app.services.audit import record_audit
from app.services.dataset import Dataset
from app.services.exercise_filter import filter_exercises
from app.services.identity import commit_or_conflict
from app.services.recommender import Recommender

MAX_PLAN_TITLE = 120
MAX_IDEMPOTENCY_KEY = 128


def utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _hash_idempotency(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hash_share_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _expected_day_count(available_days: int) -> int:
    return min(max(available_days, 1), 5)


def _title_for(request: RecommendationRequest, response: RecommendationResponse, title: Optional[str]) -> str:
    candidate = (title or "").strip() or f"Rencana {response.split_type}"
    return candidate[:MAX_PLAN_TITLE]


def _profile_from_request(request: RecommendationRequest) -> UserProfile:
    return UserProfile(
        gender=request.gender,
        height_cm=request.height_cm,
        weight_kg=request.weight_kg,
        injuries=tuple(request.injuries),
        available_days=request.available_days,
        preferred_body_part=tuple(request.preferred_body_part),
        preferred_equipment=tuple(request.preferred_equipment),
        seed=request.seed,
    )


def _dataset_index(dataset: Dataset) -> Dict[str, Exercise]:
    return {exercise.exercise_id: exercise for exercise in dataset.exercises}


def _validate_response(
    response: RecommendationResponse,
    request: RecommendationRequest,
    dataset: Dataset,
) -> None:
    if response.dataset_version != dataset.version:
        raise PlanDatasetMismatchError(
            details={
                "expected": dataset.version,
                "received": response.dataset_version,
            }
        )

    expected_days = _expected_day_count(request.available_days)
    if len(response.days) != expected_days:
        raise PlanValidationError(
            "Jumlah hari pada plan tidak sesuai available_days.",
            details={"expected": expected_days, "received": len(response.days)},
        )
    if len(response.schedule) != expected_days:
        raise PlanValidationError(
            "Schedule plan tidak lengkap.",
            details={"expected": expected_days, "received": len(response.schedule)},
        )

    by_id = _dataset_index(dataset)
    injured_parts = map_injury_to_body_parts(request.injuries)
    seen_day_numbers: set[int] = set()

    for day in response.days:
        if day.day in seen_day_numbers:
            raise PlanValidationError(
                "Nomor hari pada plan duplikat.",
                details={"day": day.day},
            )
        seen_day_numbers.add(day.day)

        focus = Focus(day.day_focus)
        schedule_focus = response.schedule.get(f"day_{day.day}")
        if schedule_focus is None or Focus(schedule_focus) is not focus:
            raise PlanValidationError(
                "Schedule tidak cocok dengan fokus hari.",
                details={"day": day.day},
            )

        required = num_exercises_for_focus(focus)
        if len(day.exercises) != required:
            raise PlanValidationError(
                "Jumlah exercise pada hari tidak sesuai fokus.",
                details={"day": day.day, "expected": required, "received": len(day.exercises)},
            )

        seen_exercise_ids: set[str] = set()
        for item in day.exercises:
            if item.exercise_id in seen_exercise_ids:
                raise PlanValidationError(
                    "Exercise duplikat dalam satu hari.",
                    details={"day": day.day, "exercise_id": item.exercise_id},
                )
            seen_exercise_ids.add(item.exercise_id)

            dataset_exercise = by_id.get(item.exercise_id)
            if dataset_exercise is None:
                raise PlanValidationError(
                    "Exercise tidak ada di dataset.",
                    details={"exercise_id": item.exercise_id},
                )
            if dataset_exercise.body_part in injured_parts:
                raise PlanValidationError(
                    "Plan mengandung exercise pada area cedera.",
                    details={
                        "day": day.day,
                        "exercise_id": item.exercise_id,
                        "body_part": dataset_exercise.body_part.value,
                    },
                )
            if not is_exercise_focus(dataset_exercise.body_part, focus):
                raise PlanValidationError(
                    "Exercise tidak sesuai fokus hari.",
                    details={
                        "day": day.day,
                        "exercise_id": item.exercise_id,
                        "body_part": dataset_exercise.body_part.value,
                        "focus": focus.value,
                    },
                )


def _persist_version(
    session: Session,
    *,
    plan: Plan,
    version_number: int,
    response: RecommendationResponse,
    dataset: Dataset,
    created_by: uuid.UUID,
) -> PlanVersion:
    version = PlanVersion(
        plan_id=plan.id,
        version=version_number,
        split_type=response.split_type,
        schedule={key: Focus(value).value for key, value in response.schedule.items()},
        warnings=list(response.warnings),
        day_count=len(response.days),
        created_by=created_by,
    )
    session.add(version)
    session.flush()

    by_id = _dataset_index(dataset)
    for day in response.days:
        plan_day = PlanDay(
            plan_version_id=version.id,
            day_number=day.day,
            focus=Focus(day.day_focus).value,
        )
        session.add(plan_day)
        session.flush()

        for position, item in enumerate(day.exercises):
            exercise = by_id[item.exercise_id]
            session.add(
                PlanExercise(
                    plan_day_id=plan_day.id,
                    exercise_id=exercise.exercise_id,
                    exercise_name=exercise.exercise_name,
                    body_part=exercise.body_part.value,
                    equipment=[equipment.value for equipment in exercise.equipment],
                    primary_muscle=list(exercise.primary_muscle),
                    secondary_muscle=list(exercise.secondary_muscle),
                    image_url=exercise.image_url,
                    position=position,
                    locked=False,
                )
            )
    session.flush()
    return version


def _persist_response(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    request: RecommendationRequest,
    response: RecommendationResponse,
    title: Optional[str],
    idempotency_key: Optional[str],
    idempotency_hash: Optional[str],
    dataset: Dataset,
) -> Plan:
    plan = Plan(
        owner_user_id=owner_user_id,
        title=_title_for(request, response, title),
        status="active",
        current_version=1,
        revision=1,
        input_snapshot=request.model_dump(mode="json"),
        seed=response.seed,
        dataset_version=response.dataset_version,
        algorithm_version=response.algorithm_version,
        split_type=response.split_type,
        day_count=len(response.days),
        bmi=response.bmi,
        bmi_category=response.bmi_category,
        idempotency_key=idempotency_key,
        idempotency_hash=idempotency_hash,
    )
    session.add(plan)
    session.flush()
    _persist_version(
        session,
        plan=plan,
        version_number=1,
        response=response,
        dataset=dataset,
        created_by=owner_user_id,
    )
    return plan


def create_plan(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    request: RecommendationRequest,
    result: Optional[RecommendationResponse],
    title: Optional[str],
    idempotency_key: Optional[str],
    recommender: Recommender,
    actor_role: str,
    source: str,
) -> Plan:
    key = (idempotency_key or "").strip()[:MAX_IDEMPOTENCY_KEY] or None
    hash_payload = {
        "recommendation": request.model_dump(mode="json"),
        "result": result.model_dump(mode="json") if result is not None else None,
        "title": title,
    }
    payload_hash = _hash_idempotency(hash_payload)

    if key:
        existing = session.scalar(
            select(Plan).where(
                Plan.owner_user_id == owner_user_id,
                Plan.idempotency_key == key,
            )
        )
        if existing is not None:
            if existing.idempotency_hash != payload_hash:
                raise IdempotencyConflictError()
            return existing

    if result is None:
        generated = recommender.recommend(_profile_from_request(request))
        result = RecommendationResponse.from_plan(generated)

    _validate_response(result, request, recommender.dataset)

    plan = _persist_response(
        session,
        owner_user_id=owner_user_id,
        request=request,
        response=result,
        title=title,
        idempotency_key=key,
        idempotency_hash=payload_hash if key else None,
        dataset=recommender.dataset,
    )
    record_audit(
        session,
        actor_user_id=owner_user_id,
        actor_role=actor_role,
        action="plan.created",
        resource_type="plan",
        resource_id=str(plan.id),
        metadata={
            "source": source,
            "version": plan.current_version,
            "day_count": plan.day_count,
        },
    )

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if key:
            existing = session.scalar(
                select(Plan).where(
                    Plan.owner_user_id == owner_user_id,
                    Plan.idempotency_key == key,
                )
            )
            if existing is not None and existing.idempotency_hash == payload_hash:
                return existing
        raise ConflictError("Plan gagal disimpan karena konflik data.") from exc
    return plan


def get_owned_plan(
    session: Session,
    *,
    plan_id: uuid.UUID,
    owner_user_id: uuid.UUID,
) -> Plan:
    plan = session.scalar(
        select(Plan).where(
            Plan.id == plan_id,
            Plan.owner_user_id == owner_user_id,
            Plan.deleted_at.is_(None),
        )
    )
    if plan is None:
        raise PlanNotFoundError()
    return plan


def get_current_version(session: Session, plan: Plan) -> PlanVersion:
    version = session.scalar(
        select(PlanVersion).where(
            PlanVersion.plan_id == plan.id,
            PlanVersion.version == plan.current_version,
        )
    )
    if version is None:
        raise PlanNotFoundError("Versi plan tidak ditemukan.")
    return version


def load_days(session: Session, version_id: uuid.UUID) -> List[PlanDay]:
    return list(
        session.scalars(
            select(PlanDay)
            .options(selectinload(PlanDay.exercises))
            .where(PlanDay.plan_version_id == version_id)
            .order_by(PlanDay.day_number)
        ).all()
    )


def _exercise_out(item: PlanExercise) -> PlanExerciseOut:
    return PlanExerciseOut(
        id=item.id,
        exercise_id=item.exercise_id,
        exercise_name=item.exercise_name,
        body_part=BodyPart(item.body_part),
        equipment=[Equipment(value) for value in item.equipment],
        primary_muscle=item.primary_muscle,
        secondary_muscle=item.secondary_muscle,
        exercise_image=item.image_url,
        locked=item.locked,
    )


def _day_out(day: PlanDay) -> PlanDayOut:
    return PlanDayOut(
        day=day.day_number,
        day_focus=day.focus,
        exercises=[_exercise_out(item) for item in day.exercises],
    )


def serialize_plan(
    session: Session,
    plan: Plan,
    *,
    version: Optional[PlanVersion] = None,
) -> PlanResponse:
    plan_version = version or get_current_version(session, plan)
    days = load_days(session, plan_version.id)
    return PlanResponse(
        id=plan.id,
        title=plan.title,
        status=plan.status,
        current_version=plan.current_version,
        revision=plan.revision,
        input=plan.input_snapshot,
        bmi=float(plan.bmi) if plan.bmi is not None else None,
        bmi_category=plan.bmi_category,
        split_type=plan_version.split_type,
        schedule=dict(plan_version.schedule),
        days=[_day_out(day) for day in days],
        seed=plan.seed,
        dataset_version=plan.dataset_version,
        algorithm_version=plan.algorithm_version,
        warnings=list(plan_version.warnings or []),
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def serialize_summary(plan: Plan) -> PlanSummary:
    return PlanSummary(
        id=plan.id,
        title=plan.title,
        status=plan.status,
        current_version=plan.current_version,
        revision=plan.revision,
        split_type=plan.split_type,
        day_count=plan.day_count,
        seed=plan.seed,
        dataset_version=plan.dataset_version,
        algorithm_version=plan.algorithm_version,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def serialize_public_plan(
    session: Session,
    plan: Plan,
    share: PlanShare,
) -> PublicPlanResponse:
    plan_version = get_current_version(session, plan)
    days = load_days(session, plan_version.id)
    return PublicPlanResponse(
        title=plan.title,
        split_type=plan_version.split_type,
        schedule=dict(plan_version.schedule),
        days=[_day_out(day) for day in days],
        seed=plan.seed,
        dataset_version=plan.dataset_version,
        algorithm_version=plan.algorithm_version,
        warnings=list(plan_version.warnings or []),
        expires_at=share.expires_at,
    )


def list_plans(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    limit: int,
    cursor: Optional[str],
) -> Tuple[List[Plan], Optional[str]]:
    limit = min(max(limit, 1), 50)
    stmt = (
        select(Plan)
        .where(Plan.owner_user_id == owner_user_id, Plan.deleted_at.is_(None))
        .order_by(Plan.created_at.desc(), Plan.id.desc())
    )

    if cursor:
        try:
            cursor_id = uuid.UUID(cursor)
        except ValueError as exc:
            raise InvalidCursorError() from exc
        cursor_plan = session.scalar(
            select(Plan).where(
                Plan.id == cursor_id,
                Plan.owner_user_id == owner_user_id,
                Plan.deleted_at.is_(None),
            )
        )
        if cursor_plan is None:
            raise InvalidCursorError()
        stmt = stmt.where(
            (Plan.created_at < cursor_plan.created_at)
            | (
                (Plan.created_at == cursor_plan.created_at)
                & (Plan.id < cursor_plan.id)
            )
        )

    plans = list(session.scalars(stmt.limit(limit + 1)).all())
    next_cursor = str(plans[limit - 1].id) if len(plans) > limit else None
    return plans[:limit], next_cursor


def _copy_version(
    session: Session,
    *,
    plan: Plan,
    source: PlanVersion,
    created_by: uuid.UUID,
) -> Tuple[PlanVersion, Dict[uuid.UUID, PlanExercise], Dict[uuid.UUID, PlanDay]]:
    new_version = PlanVersion(
        plan_id=plan.id,
        version=source.version + 1,
        split_type=source.split_type,
        schedule=dict(source.schedule),
        warnings=list(source.warnings or []),
        day_count=source.day_count,
        created_by=created_by,
    )
    session.add(new_version)
    session.flush()

    old_days = load_days(session, source.id)
    day_map: Dict[uuid.UUID, PlanDay] = {}
    exercise_map: Dict[uuid.UUID, PlanExercise] = {}

    for old_day in old_days:
        new_day = PlanDay(
            plan_version_id=new_version.id,
            day_number=old_day.day_number,
            focus=old_day.focus,
        )
        session.add(new_day)
        session.flush()
        day_map[old_day.id] = new_day

        for old_exercise in old_day.exercises:
            new_exercise = PlanExercise(
                plan_day_id=new_day.id,
                exercise_id=old_exercise.exercise_id,
                exercise_name=old_exercise.exercise_name,
                body_part=old_exercise.body_part,
                equipment=list(old_exercise.equipment),
                primary_muscle=list(old_exercise.primary_muscle),
                secondary_muscle=list(old_exercise.secondary_muscle),
                image_url=old_exercise.image_url,
                position=old_exercise.position,
                locked=old_exercise.locked,
            )
            session.add(new_exercise)
            session.flush()
            exercise_map[old_exercise.id] = new_exercise

    return new_version, exercise_map, day_map


def _fill_exercise(target: PlanExercise, source: Exercise) -> None:
    target.exercise_id = source.exercise_id
    target.exercise_name = source.exercise_name
    target.body_part = source.body_part.value
    target.equipment = [equipment.value for equipment in source.equipment]
    target.primary_muscle = list(source.primary_muscle)
    target.secondary_muscle = list(source.secondary_muscle)
    target.image_url = source.image_url


def _find_version_exercise(
    days: Sequence[PlanDay],
    exercise_id: Optional[uuid.UUID],
) -> Tuple[PlanDay, PlanExercise]:
    if exercise_id is None:
        raise PlanValidationError("plan_exercise_id wajib diisi.")
    for day in days:
        for exercise in day.exercises:
            if exercise.id == exercise_id:
                return day, exercise
    raise PlanValidationError(
        "Exercise tidak ditemukan pada versi plan ini.",
        details={"plan_exercise_id": str(exercise_id)},
    )


def _choose_replacement(
    *,
    dataset: Dataset,
    plan: Plan,
    days: Sequence[PlanDay],
    old_day: PlanDay,
    old_exercise: PlanExercise,
    explicit_exercise_id: Optional[str],
    injuries: Sequence[str],
    equipment: Sequence[str],
    focus: Focus,
) -> Exercise:
    by_id = _dataset_index(dataset)
    injured_parts = map_injury_to_body_parts(injuries)
    used_ids = {
        exercise.exercise_id
        for day in days
        for exercise in day.exercises
        if exercise.id != old_exercise.id
    }

    if explicit_exercise_id:
        replacement = by_id.get(explicit_exercise_id)
        if replacement is None:
            raise PlanValidationError(
                "Exercise pengganti tidak ditemukan.",
                details={"exercise_id": explicit_exercise_id},
            )
        if replacement.body_part in injured_parts:
            raise PlanValidationError(
                "Exercise pengganti berada pada area cedera.",
                details={"exercise_id": explicit_exercise_id},
            )
        if not is_exercise_focus(replacement.body_part, focus):
            raise PlanValidationError(
                "Exercise pengganti tidak sesuai fokus hari.",
                details={"exercise_id": explicit_exercise_id, "focus": focus.value},
            )
        if replacement.exercise_id == old_exercise.exercise_id:
            raise PlanValidationError(
                "Exercise pengganti harus berbeda dari exercise saat ini.",
                details={"exercise_id": explicit_exercise_id},
            )
        if replacement.exercise_id in used_ids:
            raise PlanValidationError(
                "Exercise pengganti sudah dipakai di plan ini.",
                details={"exercise_id": explicit_exercise_id},
            )
        return replacement

    preferred_equipment = {Equipment(value) for value in equipment}
    pool = filter_exercises(
        dataset,
        focus=focus,
        injured_parts=injured_parts,
        preferred_equipment=preferred_equipment,
        required=1,
    )
    candidates = [
        exercise
        for exercise in pool
        if exercise.exercise_id not in used_ids
        and exercise.exercise_id != old_exercise.exercise_id
    ]
    if not candidates:
        candidates = [
            exercise
            for exercise in pool
            if exercise.exercise_id != old_exercise.exercise_id
        ]
    if not candidates:
        raise InsufficientPoolError(
            details={
                "day": old_day.day_number,
                "focus": focus.value,
                "reason": "no safe replacement",
            }
        )

    same_body = [
        exercise
        for exercise in candidates
        if exercise.body_part.value == old_exercise.body_part
    ]
    choices = same_body or candidates
    choices.sort(key=lambda exercise: exercise.exercise_id)
    rng = random.Random(f"{plan.id}:{plan.revision}:{old_exercise.id}")
    return rng.choice(choices)


def _generate_candidates(
    recommender: Recommender,
    *,
    focus: Focus,
    injuries: Sequence[str],
    equipment: Sequence[str],
    preferred_body_part: Sequence[str],
    seed: int,
    needed: int,
) -> List[Exercise]:
    if needed <= 0:
        return []

    candidates: List[Exercise] = []
    seen: set[str] = set()

    preferred_equipment = tuple(Equipment(value) for value in equipment)
    preferred_parts = tuple(BodyPart(value) for value in preferred_body_part)

    for offset in range(8):
        try:
            generated, _ = recommender.recommend_day(
                focus=focus,
                injuries=tuple(injuries),
                preferred_equipment=preferred_equipment,
                preferred_body_part=preferred_parts,
                seed=(seed + offset) % (2**32),
            )
        except InsufficientPoolError:
            break
        for exercise in generated.exercises:
            if exercise.exercise_id not in seen:
                seen.add(exercise.exercise_id)
                candidates.append(exercise)
        if len(candidates) >= needed:
            return candidates[:needed]

    pool = filter_exercises(
        recommender.dataset,
        focus=focus,
        injured_parts=map_injury_to_body_parts(injuries),
        preferred_equipment=set(preferred_equipment),
        required=needed,
    )
    for exercise in sorted(pool, key=lambda item: item.exercise_id):
        if exercise.exercise_id not in seen:
            seen.add(exercise.exercise_id)
            candidates.append(exercise)
            if len(candidates) >= needed:
                return candidates[:needed]

    raise InsufficientPoolError(
        details={
            "focus": focus.value,
            "required": needed,
            "available": len(candidates),
        }
    )


def update_plan(
    session: Session,
    *,
    plan: Plan,
    payload: PlanUpdateRequest,
    expected_revision: Optional[int],
    recommender: Recommender,
    actor_role: str,
) -> Plan:
    if expected_revision is None:
        raise PreconditionRequiredError()
    if expected_revision != plan.revision:
        raise PlanRevisionConflictError(
            details={"current_revision": plan.revision}
        )

    current_version = get_current_version(session, plan)
    days = load_days(session, current_version.id)
    new_version, exercise_map, day_map = _copy_version(
        session,
        plan=plan,
        source=current_version,
        created_by=plan.owner_user_id,
    )

    action_metadata: Dict[str, Any] = {"action": payload.action}

    if payload.action == "lock":
        if payload.locked is None:
            raise PlanValidationError("locked wajib diisi untuk action lock.")
        old_day, old_exercise = _find_version_exercise(days, payload.plan_exercise_id)
        new_exercise = exercise_map[old_exercise.id]
        new_exercise.locked = bool(payload.locked)
        action_metadata.update(
            {
                "day": old_day.day_number,
                "locked": bool(payload.locked),
            }
        )

    elif payload.action == "swap":
        old_day, old_exercise = _find_version_exercise(days, payload.plan_exercise_id)
        if old_exercise.locked:
            raise ExerciseLockedError()
        input_snapshot = plan.input_snapshot or {}
        focus = Focus(old_day.focus)
        replacement = _choose_replacement(
            dataset=recommender.dataset,
            plan=plan,
            days=days,
            old_day=old_day,
            old_exercise=old_exercise,
            explicit_exercise_id=payload.replacement_exercise_id,
            injuries=tuple(input_snapshot.get("injuries", [])),
            equipment=tuple(input_snapshot.get("preferred_equipment", [])),
            focus=focus,
        )
        new_exercise = exercise_map[old_exercise.id]
        _fill_exercise(new_exercise, replacement)
        new_exercise.locked = False
        action_metadata.update(
            {
                "day": old_day.day_number,
                "from_exercise_id": old_exercise.exercise_id,
                "to_exercise_id": replacement.exercise_id,
            }
        )

    elif payload.action == "regenerate_day":
        if payload.day is None:
            raise PlanValidationError("day wajib diisi untuk action regenerate_day.")
        regen_day = next((day for day in days if day.day_number == payload.day), None)
        if regen_day is None:
            raise PlanValidationError(
                "Hari tidak ditemukan pada plan.",
                details={"day": payload.day},
            )

        locked_positions = {
            exercise.position for exercise in regen_day.exercises if exercise.locked
        }
        needed = len(regen_day.exercises) - len(locked_positions)
        input_snapshot = plan.input_snapshot or {}
        candidates = _generate_candidates(
            recommender,
            focus=Focus(regen_day.focus),
            injuries=tuple(input_snapshot.get("injuries", [])),
            equipment=tuple(input_snapshot.get("preferred_equipment", [])),
            preferred_body_part=tuple(input_snapshot.get("preferred_body_part", [])),
            seed=plan.seed + plan.revision,
            needed=needed,
        )

        candidate_index = 0
        for old_exercise in regen_day.exercises:
            if old_exercise.position in locked_positions:
                continue
            new_exercise = exercise_map[old_exercise.id]
            _fill_exercise(new_exercise, candidates[candidate_index])
            new_exercise.locked = False
            candidate_index += 1

        action_metadata.update(
            {
                "day": regen_day.day_number,
                "locked_preserved": len(locked_positions),
            }
        )

    plan.current_version = new_version.version
    plan.revision += 1
    plan.updated_at = utcnow()

    record_audit(
        session,
        actor_user_id=plan.owner_user_id,
        actor_role=actor_role,
        action="plan.updated",
        resource_type="plan",
        resource_id=str(plan.id),
        metadata={**action_metadata, "version": new_version.version},
    )
    commit_or_conflict(session)
    return plan


def delete_plan(
    session: Session,
    *,
    plan: Plan,
    actor_role: str,
) -> None:
    now = utcnow()
    plan.status = "deleted"
    plan.deleted_at = now
    plan.idempotency_key = None
    plan.idempotency_hash = None
    plan.revision += 1

    shares = list(
        session.scalars(
            select(PlanShare).where(
                PlanShare.plan_id == plan.id,
                PlanShare.revoked_at.is_(None),
            )
        ).all()
    )
    for share in shares:
        share.revoked_at = now

    record_audit(
        session,
        actor_user_id=plan.owner_user_id,
        actor_role=actor_role,
        action="plan.deleted",
        resource_type="plan",
        resource_id=str(plan.id),
        metadata={"version": plan.current_version, "revoked_shares": len(shares)},
    )
    commit_or_conflict(session)


def create_share(
    session: Session,
    *,
    plan: Plan,
    expires_in_days: int,
    actor_role: str,
) -> Tuple[str, PlanShare]:
    token = secrets.token_urlsafe(32)
    share = PlanShare(
        plan_id=plan.id,
        token_hash=_hash_share_token(token),
        expires_at=utcnow() + timedelta(days=expires_in_days),
    )
    session.add(share)
    record_audit(
        session,
        actor_user_id=plan.owner_user_id,
        actor_role=actor_role,
        action="plan.shared",
        resource_type="plan",
        resource_id=str(plan.id),
        metadata={"expires_in_days": expires_in_days},
    )
    commit_or_conflict(session)
    return token, share


def revoke_shares(
    session: Session,
    *,
    plan: Plan,
    actor_role: str,
) -> int:
    now = utcnow()
    shares = list(
        session.scalars(
            select(PlanShare).where(
                PlanShare.plan_id == plan.id,
                PlanShare.revoked_at.is_(None),
            )
        ).all()
    )
    for share in shares:
        share.revoked_at = now
    record_audit(
        session,
        actor_user_id=plan.owner_user_id,
        actor_role=actor_role,
        action="plan.share_revoked",
        resource_type="plan",
        resource_id=str(plan.id),
        metadata={"revoked": len(shares)},
    )
    commit_or_conflict(session)
    return len(shares)


def resolve_share(session: Session, token: str) -> Tuple[Plan, PlanShare]:
    share = session.scalar(
        select(PlanShare)
        .join(Plan, Plan.id == PlanShare.plan_id)
        .where(
            PlanShare.token_hash == _hash_share_token(token),
            PlanShare.revoked_at.is_(None),
            Plan.deleted_at.is_(None),
        )
    )
    if share is None:
        raise ShareNotFoundError()
    if _as_utc(share.expires_at) <= utcnow():
        raise ShareNotFoundError()
    return share.plan, share


def list_versions(session: Session, plan: Plan) -> List[PlanVersionOut]:
    versions = list(
        session.scalars(
            select(PlanVersion)
            .where(PlanVersion.plan_id == plan.id)
            .order_by(PlanVersion.version.desc())
        ).all()
    )
    return [
        PlanVersionOut(
            version=version.version,
            split_type=version.split_type,
            schedule=dict(version.schedule),
            warnings=list(version.warnings or []),
            day_count=version.day_count,
            created_at=version.created_at,
        )
        for version in versions
    ]


def _pdf_safe(value: str) -> str:
    """Keep ReportLab's built-in Type1 fonts from failing on exotic text."""

    return value.encode("latin-1", "replace").decode("latin-1")


def _pdf_bytes(plan: Plan, version: PlanVersion, days: Sequence[PlanDay]) -> bytes:
    buffer = io.BytesIO()
    styles = getSampleStyleSheet()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=plan.title,
        author="JYMZ",
    )

    story = [
        Paragraph(xml_escape(_pdf_safe(plan.title)), styles["Title"]),
        Paragraph(
            xml_escape(
                _pdf_safe(f"{version.split_type} · versi {version.version} · seed {plan.seed}")
            ),
            styles["Normal"],
        ),
        Spacer(1, 4 * mm),
    ]

    for day in days:
        story.append(
            Paragraph(
                xml_escape(_pdf_safe(f"Day {day.day_number} - {day.focus}")),
                styles["Heading2"],
            )
        )
        rows = [["Exercise", "Body part", "Equipment"]]
        for exercise in day.exercises:
            rows.append(
                [
                    Paragraph(
                        xml_escape(_pdf_safe(exercise.exercise_name)),
                        styles["BodyText"],
                    ),
                    Paragraph(
                        xml_escape(_pdf_safe(exercise.body_part)),
                        styles["BodyText"],
                    ),
                    Paragraph(
                        xml_escape(_pdf_safe(", ".join(exercise.equipment))),
                        styles["BodyText"],
                    ),
                ]
            )
        table = Table(rows, colWidths=[82 * mm, 38 * mm, 52 * mm], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8E8E8")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 5 * mm))

    story.append(
        Paragraph(
            _pdf_safe("Plan ini bukan saran medis. Hentikan latihan jika terasa nyeri."),
            styles["Italic"],
        )
    )
    if version.warnings:
        story.append(Spacer(1, 3 * mm))
        story.append(
            Paragraph(
                xml_escape(_pdf_safe("Catatan: " + "; ".join(version.warnings))),
                styles["Italic"],
            )
        )

    document.build(story)
    return buffer.getvalue()


def _ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _next_monday() -> date:
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def _ics_bytes(plan: Plan, version: PlanVersion, days: Sequence[PlanDay]) -> bytes:
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    start = _next_monday()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//JYMZ//Training Plan//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    for index, day in enumerate(days):
        event_date = start + timedelta(days=index)
        next_date = event_date + timedelta(days=1)
        summary = f"JYMZ Day {day.day_number} - {day.focus}"
        description = "; ".join(
            f"{exercise.exercise_name} ({exercise.body_part})"
            for exercise in day.exercises
        )
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{plan.id}-v{version.version}-day-{day.day_number}@jymz",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{event_date.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{next_date.strftime('%Y%m%d')}",
                f"SUMMARY:{_ics_escape(summary)}",
                f"DESCRIPTION:{_ics_escape(description)}",
                "STATUS:CONFIRMED",
                "TRANSP:OPAQUE",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def export_pdf(
    session: Session,
    *,
    plan: Plan,
    actor_role: str,
) -> bytes:
    version = get_current_version(session, plan)
    days = load_days(session, version.id)
    content = _pdf_bytes(plan, version, days)
    record_audit(
        session,
        actor_user_id=plan.owner_user_id,
        actor_role=actor_role,
        action="plan.exported",
        resource_type="plan",
        resource_id=str(plan.id),
        metadata={"format": "pdf", "version": version.version},
    )
    commit_or_conflict(session)
    return content


def export_ics(
    session: Session,
    *,
    plan: Plan,
    actor_role: str,
) -> bytes:
    version = get_current_version(session, plan)
    days = load_days(session, version.id)
    content = _ics_bytes(plan, version, days)
    record_audit(
        session,
        actor_user_id=plan.owner_user_id,
        actor_role=actor_role,
        action="plan.exported",
        resource_type="plan",
        resource_id=str(plan.id),
        metadata={"format": "ics", "version": version.version},
    )
    commit_or_conflict(session)
    return content


def calendar_ics_for_plan(session: Session, plan: Plan) -> bytes:
    version = get_current_version(session, plan)
    days = load_days(session, version.id)
    return _ics_bytes(plan, version, days)


def build_share_response(
    token: str,
    share: PlanShare,
    share_url: str,
) -> PlanShareResponse:
    return PlanShareResponse(
        token=token,
        expires_at=share.expires_at,
        share_url=share_url,
    )
