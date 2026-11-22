"""P1.1 progress aggregates, personal records, and insights."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Dict, Iterable, List, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import ProgressValidationError
from app.db.models import (
    DailyMetric,
    PersonalRecord,
    Profile,
    SetLog,
    WeeklyReview,
    WorkoutExercise,
    WorkoutSession,
)
from app.schemas.progress import (
    DailyMetricOut,
    InsightsResponse,
    PersonalRecordOut,
    ProgressHistoryResponse,
    ProgressResponse,
    ProgressTotals,
    WeeklyReviewOut,
)
from app.services.identity import commit_or_conflict
from app.services.workouts import list_workouts, serialize_summary

MAX_RANGE_DAYS = 366


def utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _profile_timezone(session: Session, user_id: uuid.UUID) -> str:
    profile = session.get(Profile, user_id)
    return profile.timezone if profile and profile.timezone else "UTC"


def resolve_timezone(session: Session, user_id: uuid.UUID, requested: Optional[str]) -> str:
    candidate = requested or _profile_timezone(session, user_id)
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ProgressValidationError(
            "Timezone harus nama IANA yang valid.",
            details={"timezone": candidate},
        ) from exc
    return candidate


def _date_range(
    timezone_name: str,
    from_date: Optional[date],
    to_date: Optional[date],
) -> Tuple[date, date]:
    tz = ZoneInfo(timezone_name)
    today = datetime.now(tz).date()
    end = to_date or today
    start = from_date or (end - timedelta(days=29))
    if start > end:
        raise ProgressValidationError("from_date harus sebelum atau sama dengan to_date.")
    if (end - start).days > MAX_RANGE_DAYS:
        raise ProgressValidationError(
            "Rentang progress terlalu besar.",
            details={"max_days": MAX_RANGE_DAYS},
        )
    return start, end


def _utc_bounds(
    from_date: date,
    to_date: date,
    timezone_name: str,
) -> Tuple[datetime, datetime]:
    tz = ZoneInfo(timezone_name)
    start = datetime.combine(from_date, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=tz).astimezone(
        UTC
    )
    return start, end


def _add_dict(target: Dict[str, float], source: Mapping[str, object]) -> None:
    for key, value in source.items():
        target[key] = round(target.get(key, 0.0) + float(value), 2)  # type: ignore[arg-type]


@dataclass
class _DailyBucket:
    workouts: int = 0
    sets: int = 0
    reps: int = 0
    volume: float = 0.0
    duration: int = 0
    sets_by_part: Dict[str, float] = field(default_factory=dict)
    volume_by_part: Dict[str, float] = field(default_factory=dict)


@dataclass
class _RecordBest:
    exercise_id: str
    exercise_name: str
    record_type: str
    value: float
    reps: Optional[int]
    weight_kg: Optional[float]
    achieved_at: datetime
    set_log_id: Optional[uuid.UUID]


def _completed_workouts(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    from_date: date,
    to_date: date,
    timezone_name: str,
) -> List[WorkoutSession]:
    start, end = _utc_bounds(from_date, to_date, timezone_name)
    return list(
        session.scalars(
            select(WorkoutSession)
            .options(
                selectinload(WorkoutSession.exercises).selectinload(
                    WorkoutExercise.sets
                )
            )
            .where(
                WorkoutSession.owner_user_id == owner_user_id,
                WorkoutSession.status == "completed",
                WorkoutSession.deleted_at.is_(None),
                WorkoutSession.completed_at.is_not(None),
                WorkoutSession.completed_at >= start,
                WorkoutSession.completed_at < end,
            )
            .order_by(WorkoutSession.completed_at)
        ).all()
    )


def _workout_rollup(workout: WorkoutSession) -> Tuple[int, int, float, int, Dict[str, int], Dict[str, float]]:
    total_sets = 0
    total_reps = 0
    total_volume = 0.0
    sets_by_part: Dict[str, int] = {}
    volume_by_part: Dict[str, float] = {}

    for exercise in workout.exercises:
        for set_log in exercise.sets:
            if set_log.deleted_at is not None or not set_log.completed:
                continue
            reps = int(set_log.reps or 0)
            weight = float(set_log.weight_kg or 0)
            volume = reps * weight
            total_sets += 1
            total_reps += reps
            total_volume += volume
            sets_by_part[exercise.body_part] = sets_by_part.get(exercise.body_part, 0) + 1
            volume_by_part[exercise.body_part] = round(
                volume_by_part.get(exercise.body_part, 0.0) + volume, 2
            )

    return (
        total_sets,
        total_reps,
        round(total_volume, 2),
        int(workout.duration_seconds or 0),
        sets_by_part,
        volume_by_part,
    )


def _rebuild_daily_metrics(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    from_date: date,
    to_date: date,
    timezone_name: str,
) -> None:
    session.execute(
        delete(DailyMetric).where(
            DailyMetric.owner_user_id == owner_user_id,
            DailyMetric.metric_date >= from_date,
            DailyMetric.metric_date <= to_date,
        )
    )
    workouts = _completed_workouts(
        session,
        owner_user_id=owner_user_id,
        from_date=from_date,
        to_date=to_date,
        timezone_name=timezone_name,
    )
    tz = ZoneInfo(timezone_name)
    grouped: Dict[date, _DailyBucket] = {}

    for workout in workouts:
        completed_at = workout.completed_at or workout.started_at
        local_date = _as_utc(completed_at).astimezone(tz).date()
        if local_date < from_date or local_date > to_date:
            continue
        bucket = grouped.setdefault(local_date, _DailyBucket())
        (
            workout_sets,
            workout_reps,
            workout_volume,
            duration,
            sets_by_part,
            volume_by_part,
        ) = _workout_rollup(workout)

        bucket.workouts += 1
        bucket.sets += workout_sets
        bucket.reps += workout_reps
        bucket.volume = round(bucket.volume + workout_volume, 2)
        bucket.duration += duration
        _add_dict(bucket.sets_by_part, sets_by_part)
        _add_dict(bucket.volume_by_part, volume_by_part)

    for metric_date, bucket in grouped.items():
        session.add(
            DailyMetric(
                owner_user_id=owner_user_id,
                metric_date=metric_date,
                timezone=timezone_name,
                workouts_completed=bucket.workouts,
                total_sets=bucket.sets,
                total_reps=bucket.reps,
                total_volume_kg=bucket.volume,
                duration_seconds=bucket.duration,
                sets_by_body_part={
                    key: int(value) for key, value in bucket.sets_by_part.items()
                },
                volume_by_body_part={
                    key: round(float(value), 2)
                    for key, value in bucket.volume_by_part.items()
                },
            )
        )
    session.flush()


def _week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _weekly_summary(workouts: int, sets: int, volume: float, parts: Dict[str, float]) -> str:
    top_part = max(parts.items(), key=lambda item: item[1])[0] if parts else None
    base = f"{workouts} workout, {sets} set, volume {round(volume, 2)} kg."
    if top_part:
        return f"{base} Volume terbesar: {top_part}."
    return base


def _rebuild_weekly_reviews(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    from_date: date,
    to_date: date,
    timezone_name: str,
) -> None:
    week_from = _week_start(from_date)
    week_to = _week_start(to_date)
    session.execute(
        delete(WeeklyReview).where(
            WeeklyReview.owner_user_id == owner_user_id,
            WeeklyReview.week_start >= week_from,
            WeeklyReview.week_start <= week_to,
        )
    )

    metrics = list(
        session.scalars(
            select(DailyMetric)
            .where(
                DailyMetric.owner_user_id == owner_user_id,
                DailyMetric.metric_date >= from_date,
                DailyMetric.metric_date <= to_date,
            )
            .order_by(DailyMetric.metric_date)
        ).all()
    )
    grouped: Dict[date, List[DailyMetric]] = {}
    for metric in metrics:
        grouped.setdefault(_week_start(metric.metric_date), []).append(metric)

    for week_start, rows in grouped.items():
        sets_by_part: Dict[str, float] = {}
        volume_by_part: Dict[str, float] = {}
        for row in rows:
            _add_dict(sets_by_part, row.sets_by_body_part or {})
            _add_dict(volume_by_part, row.volume_by_body_part or {})
        workouts = sum(row.workouts_completed for row in rows)
        sets = sum(row.total_sets for row in rows)
        volume = round(sum(float(row.total_volume_kg or 0) for row in rows), 2)
        session.add(
            WeeklyReview(
                owner_user_id=owner_user_id,
                week_start=week_start,
                timezone=timezone_name,
                workouts_completed=workouts,
                total_sets=sets,
                total_reps=sum(row.total_reps for row in rows),
                total_volume_kg=volume,
                duration_seconds=sum(row.duration_seconds for row in rows),
                sets_by_body_part={
                    key: int(value) for key, value in sets_by_part.items()
                },
                volume_by_body_part={
                    key: round(value, 2) for key, value in volume_by_part.items()
                },
                summary=_weekly_summary(workouts, sets, volume, volume_by_part),
            )
        )
    session.flush()


def _rebuild_personal_records(session: Session, *, owner_user_id: uuid.UUID) -> None:
    session.execute(
        delete(PersonalRecord).where(PersonalRecord.owner_user_id == owner_user_id)
    )
    rows = session.execute(
        select(SetLog, WorkoutExercise)
        .join(WorkoutExercise, WorkoutExercise.id == SetLog.workout_exercise_id)
        .join(WorkoutSession, WorkoutSession.id == WorkoutExercise.workout_session_id)
        .where(
            SetLog.owner_user_id == owner_user_id,
            SetLog.deleted_at.is_(None),
            SetLog.completed.is_(True),
            WorkoutSession.status == "completed",
            WorkoutSession.deleted_at.is_(None),
        )
    ).all()

    best: Dict[Tuple[str, str], _RecordBest] = {}
    for set_log, exercise in rows:
        reps = set_log.reps
        weight = float(set_log.weight_kg) if set_log.weight_kg is not None else None
        achieved_at = _as_utc(set_log.created_at)
        candidates: List[Tuple[str, float]] = []
        if weight is not None:
            candidates.append(("max_weight", weight))
        if reps is not None:
            candidates.append(("max_reps", float(reps)))
        if reps is not None and weight is not None:
            candidates.append(("max_volume", float(reps) * weight))

        for record_type, value in candidates:
            key = (exercise.exercise_id, record_type)
            current = best.get(key)
            if (
                current is None
                or value > current.value
                or (value == current.value and achieved_at > current.achieved_at)
            ):
                best[key] = _RecordBest(
                    exercise_id=exercise.exercise_id,
                    exercise_name=exercise.exercise_name,
                    record_type=record_type,
                    value=round(value, 2),
                    reps=reps,
                    weight_kg=weight,
                    achieved_at=achieved_at,
                    set_log_id=set_log.id,
                )

    for item in best.values():
        session.add(
            PersonalRecord(
                owner_user_id=owner_user_id,
                exercise_id=item.exercise_id,
                exercise_name=item.exercise_name,
                record_type=item.record_type,
                value=item.value,
                reps=item.reps,
                weight_kg=item.weight_kg,
                achieved_at=item.achieved_at,
                set_log_id=item.set_log_id,
            )
        )
    session.flush()


def refresh_progress(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    from_date: date,
    to_date: date,
    timezone_name: str,
) -> None:
    _rebuild_daily_metrics(
        session,
        owner_user_id=owner_user_id,
        from_date=from_date,
        to_date=to_date,
        timezone_name=timezone_name,
    )
    _rebuild_weekly_reviews(
        session,
        owner_user_id=owner_user_id,
        from_date=from_date,
        to_date=to_date,
        timezone_name=timezone_name,
    )
    _rebuild_personal_records(session, owner_user_id=owner_user_id)
    commit_or_conflict(session)


def _streak_days(metrics: Iterable[DailyMetric], timezone_name: str) -> int:
    active = {metric.metric_date for metric in metrics if metric.workouts_completed > 0}
    if not active:
        return 0
    today = datetime.now(ZoneInfo(timezone_name)).date()
    cursor = today if today in active else today - timedelta(days=1)
    streak = 0
    while cursor in active:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _sum_parts(metrics: Iterable[DailyMetric], field: str) -> Dict[str, float]:
    result: Dict[str, float] = {}
    for metric in metrics:
        _add_dict(result, getattr(metric, field) or {})
    return result


def get_progress(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    from_date: Optional[date],
    to_date: Optional[date],
    timezone_name: Optional[str],
) -> ProgressResponse:
    timezone_value = resolve_timezone(session, owner_user_id, timezone_name)
    start, end = _date_range(timezone_value, from_date, to_date)
    refresh_progress(
        session,
        owner_user_id=owner_user_id,
        from_date=start,
        to_date=end,
        timezone_name=timezone_value,
    )
    metrics = list(
        session.scalars(
            select(DailyMetric)
            .where(
                DailyMetric.owner_user_id == owner_user_id,
                DailyMetric.metric_date >= start,
                DailyMetric.metric_date <= end,
            )
            .order_by(DailyMetric.metric_date)
        ).all()
    )
    totals = ProgressTotals(
        workouts_completed=sum(metric.workouts_completed for metric in metrics),
        total_sets=sum(metric.total_sets for metric in metrics),
        total_reps=sum(metric.total_reps for metric in metrics),
        total_volume_kg=round(
            sum(float(metric.total_volume_kg or 0) for metric in metrics), 2
        ),
        duration_seconds=sum(metric.duration_seconds for metric in metrics),
    )
    return ProgressResponse(
        timezone=timezone_value,
        from_date=start,
        to_date=end,
        totals=totals,
        days=[
            DailyMetricOut(
                date=metric.metric_date,
                workouts_completed=metric.workouts_completed,
                total_sets=metric.total_sets,
                total_reps=metric.total_reps,
                total_volume_kg=float(metric.total_volume_kg or 0),
                duration_seconds=metric.duration_seconds,
                sets_by_body_part={
                    key: int(value) for key, value in (metric.sets_by_body_part or {}).items()
                },
                volume_by_body_part={
                    key: round(float(value), 2)
                    for key, value in (metric.volume_by_body_part or {}).items()
                },
            )
            for metric in metrics
        ],
        sets_by_body_part={
            key: int(value)
            for key, value in _sum_parts(metrics, "sets_by_body_part").items()
        },
        volume_by_body_part=_sum_parts(metrics, "volume_by_body_part"),
        streak_days=_streak_days(metrics, timezone_value),
    )


def get_progress_history(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    limit: int,
    cursor: Optional[str],
) -> ProgressHistoryResponse:
    workouts, next_cursor = list_workouts(
        session,
        owner_user_id=owner_user_id,
        limit=limit,
        cursor=cursor,
        status_filter="completed",
    )
    return ProgressHistoryResponse(
        items=[serialize_summary(workout) for workout in workouts],
        next_cursor=next_cursor,
    )


def _serialize_weekly(review: WeeklyReview) -> WeeklyReviewOut:
    return WeeklyReviewOut(
        week_start=review.week_start,
        timezone=review.timezone,
        workouts_completed=review.workouts_completed,
        total_sets=review.total_sets,
        total_reps=review.total_reps,
        total_volume_kg=float(review.total_volume_kg or 0),
        duration_seconds=review.duration_seconds,
        sets_by_body_part={
            key: int(value) for key, value in (review.sets_by_body_part or {}).items()
        },
        volume_by_body_part={
            key: round(float(value), 2)
            for key, value in (review.volume_by_body_part or {}).items()
        },
        summary=review.summary,
    )


def get_insights(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    timezone_name: Optional[str],
) -> InsightsResponse:
    timezone_value = resolve_timezone(session, owner_user_id, timezone_name)
    today = datetime.now(ZoneInfo(timezone_value)).date()
    start = today - timedelta(days=89)
    refresh_progress(
        session,
        owner_user_id=owner_user_id,
        from_date=start,
        to_date=today,
        timezone_name=timezone_value,
    )
    metrics = list(
        session.scalars(
            select(DailyMetric)
            .where(
                DailyMetric.owner_user_id == owner_user_id,
                DailyMetric.metric_date >= start,
                DailyMetric.metric_date <= today,
            )
            .order_by(DailyMetric.metric_date)
        ).all()
    )
    last_28_start = today - timedelta(days=27)
    last_28 = [metric for metric in metrics if metric.metric_date >= last_28_start]
    current_week_start = _week_start(today)
    current_week = session.scalar(
        select(WeeklyReview).where(
            WeeklyReview.owner_user_id == owner_user_id,
            WeeklyReview.week_start == current_week_start,
        )
    )
    records = list(
        session.scalars(
            select(PersonalRecord)
            .where(PersonalRecord.owner_user_id == owner_user_id)
            .order_by(PersonalRecord.achieved_at.desc())
            .limit(10)
        ).all()
    )
    body_part_balance = _sum_parts(last_28, "volume_by_body_part")
    workouts_last_28 = sum(metric.workouts_completed for metric in last_28)
    streak = _streak_days(metrics, timezone_value)
    summary = (
        f"28 hari terakhir: {workouts_last_28} workout, "
        f"volume {round(sum(float(metric.total_volume_kg or 0) for metric in last_28), 2)} kg, "
        f"streak {streak} hari."
    )
    if current_week and current_week.summary:
        summary = f"{summary} Minggu ini: {current_week.summary}"

    return InsightsResponse(
        timezone=timezone_value,
        streak_days=streak,
        workouts_last_28_days=workouts_last_28,
        current_week=_serialize_weekly(current_week) if current_week else None,
        body_part_balance=body_part_balance,
        personal_records=[
            PersonalRecordOut(
                exercise_id=record.exercise_id,
                exercise_name=record.exercise_name,
                record_type=record.record_type,
                value=float(record.value),
                reps=record.reps,
                weight_kg=(
                    float(record.weight_kg) if record.weight_kg is not None else None
                ),
                achieved_at=record.achieved_at,
            )
            for record in records
        ],
        summary=summary,
    )
