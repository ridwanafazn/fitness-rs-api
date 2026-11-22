"""P0.4 feedback, safety reports, admin triage, and quality metrics."""

from __future__ import annotations

import json
import logging
import statistics
import threading
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import (
    FeedbackValidationError,
    RateLimitExceededError,
    SafetyReportNotFoundError,
    SafetyReportValidationError,
    SafetyTransitionError,
)
from app.db.models import (
    AuditLog,
    Feedback,
    Plan,
    PlanExercise,
    PlanVersion,
    UnsafeReport,
    WorkoutSession,
)
from app.domain.feedback import (
    SAFETY_TRANSITIONS,
    SEVERITY_VALUES,
    STATUS_VALUES,
    SafetySeverity,
    SafetyStatus,
)
from app.schemas.feedback import (
    AuditLogOut,
    FeedbackCreate,
    FeedbackOut,
    QualitySummary,
    UnsafeReportCreate,
    UnsafeReportOut,
    UnsafeReportUpdate,
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


def _check_rate_limit(
    session: Session,
    *,
    model,
    owner_field,
    owner_id: uuid.UUID,
    limit: int,
) -> None:
    since = utcnow() - timedelta(hours=1)
    count = session.scalar(
        select(func.count())
        .select_from(model)
        .where(owner_field == owner_id, model.created_at >= since)
    )
    if int(count or 0) >= limit:
        raise RateLimitExceededError(
            "Batas jumlah kiriman per jam tercapai. Coba lagi nanti."
        )


def _resolve_feedback_context(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    payload: FeedbackCreate,
) -> Tuple[Optional[uuid.UUID], Optional[uuid.UUID]]:
    plan_id = payload.plan_id
    plan_version_id: Optional[uuid.UUID] = None

    if payload.workout_session_id is not None:
        workout = session.scalar(
            select(WorkoutSession).where(
                WorkoutSession.id == payload.workout_session_id,
                WorkoutSession.owner_user_id == owner_user_id,
                WorkoutSession.deleted_at.is_(None),
            )
        )
        if workout is None:
            raise FeedbackValidationError(
                "Workout tidak ditemukan atau bukan milik Anda.",
                details={"workout_session_id": str(payload.workout_session_id)},
            )
        if plan_id is not None and workout.plan_id != plan_id:
            raise FeedbackValidationError(
                "Workout tidak terkait dengan plan yang diberikan."
            )
        plan_id = workout.plan_id
        plan_version_id = workout.plan_version_id

    if plan_id is not None:
        plan = session.scalar(
            select(Plan).where(
                Plan.id == plan_id,
                Plan.owner_user_id == owner_user_id,
                Plan.deleted_at.is_(None),
            )
        )
        if plan is None:
            raise FeedbackValidationError(
                "Plan tidak ditemukan atau bukan milik Anda.",
                details={"plan_id": str(plan_id)},
            )
        if plan_version_id is None:
            version = session.scalar(
                select(PlanVersion).where(
                    PlanVersion.plan_id == plan.id,
                    PlanVersion.version == plan.current_version,
                )
            )
            plan_version_id = version.id if version is not None else None

    return plan_id, plan_version_id


def submit_feedback(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    payload: FeedbackCreate,
    actor_role: str,
    limit_per_hour: int,
) -> Feedback:
    plan_id, plan_version_id = _resolve_feedback_context(
        session,
        owner_user_id=owner_user_id,
        payload=payload,
    )
    _check_rate_limit(
        session,
        model=Feedback,
        owner_field=Feedback.owner_user_id,
        owner_id=owner_user_id,
        limit=limit_per_hour,
    )

    feedback = Feedback(
        owner_user_id=owner_user_id,
        plan_id=plan_id,
        plan_version_id=plan_version_id,
        workout_session_id=payload.workout_session_id,
        rating=payload.rating,
        difficulty=payload.difficulty.value if payload.difficulty else None,
        pain=bool(payload.pain),
        pain_area=payload.pain_area,
        comment=payload.comment,
    )
    session.add(feedback)
    session.flush()

    record_audit(
        session,
        actor_user_id=owner_user_id,
        actor_role=actor_role,
        action="feedback.submitted",
        resource_type="feedback",
        resource_id=str(feedback.id),
        metadata={
            "plan_id": str(plan_id) if plan_id else None,
            "workout_session_id": (
                str(payload.workout_session_id) if payload.workout_session_id else None
            ),
            "has_comment": bool(payload.comment),
        },
    )
    commit_or_conflict(session)
    return feedback


def serialize_feedback(feedback: Feedback) -> FeedbackOut:
    return FeedbackOut(
        id=feedback.id,
        plan_id=feedback.plan_id,
        plan_version_id=feedback.plan_version_id,
        workout_session_id=feedback.workout_session_id,
        rating=feedback.rating,
        difficulty=feedback.difficulty,
        pain=feedback.pain,
        pain_area=feedback.pain_area,
        comment=feedback.comment,
        created_at=feedback.created_at,
    )


def _resolve_report_context(
    session: Session,
    *,
    reporter_user_id: uuid.UUID,
    payload: UnsafeReportCreate,
    dataset: Dataset,
) -> Tuple[
    Optional[uuid.UUID],
    Optional[uuid.UUID],
    Optional[uuid.UUID],
    str,
    str,
]:
    plan_id = payload.plan_id
    plan_exercise_id = payload.plan_exercise_id
    workout_session_id = payload.workout_session_id
    derived_exercise_id: Optional[str] = None

    if workout_session_id is not None:
        workout = session.scalar(
            select(WorkoutSession).where(
                WorkoutSession.id == workout_session_id,
                WorkoutSession.owner_user_id == reporter_user_id,
                WorkoutSession.deleted_at.is_(None),
            )
        )
        if workout is None:
            raise SafetyReportValidationError(
                "Workout tidak ditemukan atau bukan milik Anda.",
                details={"workout_session_id": str(workout_session_id)},
            )
        if plan_id is not None and workout.plan_id != plan_id:
            raise SafetyReportValidationError(
                "Workout tidak terkait dengan plan yang diberikan."
            )
        plan_id = workout.plan_id

    if plan_exercise_id is not None:
        plan_exercise = session.get(PlanExercise, plan_exercise_id)
        if plan_exercise is None:
            raise SafetyReportValidationError(
                "Plan exercise tidak ditemukan.",
                details={"plan_exercise_id": str(plan_exercise_id)},
            )
        plan = plan_exercise.day.version.plan
        if plan.owner_user_id != reporter_user_id or plan.deleted_at is not None:
            raise SafetyReportValidationError(
                "Plan exercise bukan milik Anda.",
                details={"plan_exercise_id": str(plan_exercise_id)},
            )
        if plan_id is not None and plan.id != plan_id:
            raise SafetyReportValidationError(
                "Plan exercise tidak terkait dengan plan yang diberikan."
            )
        plan_id = plan.id
        derived_exercise_id = plan_exercise.exercise_id

    by_id = {exercise.exercise_id: exercise for exercise in dataset.exercises}
    exercise_id = payload.exercise_id or derived_exercise_id
    if not exercise_id:
        raise SafetyReportValidationError(
            "exercise_id tidak dapat ditentukan dari konteks report."
        )
    if derived_exercise_id and payload.exercise_id and derived_exercise_id != payload.exercise_id:
        raise SafetyReportValidationError(
            "exercise_id tidak cocok dengan plan exercise."
        )
    if plan_id is not None:
        owned_plan = session.scalar(
            select(Plan).where(
                Plan.id == plan_id,
                Plan.owner_user_id == reporter_user_id,
                Plan.deleted_at.is_(None),
            )
        )
        if owned_plan is None:
            raise SafetyReportValidationError(
                "Plan tidak ditemukan atau bukan milik Anda.",
                details={"plan_id": str(plan_id)},
            )
    exercise = by_id.get(exercise_id)
    if exercise is None:
        raise SafetyReportValidationError(
            "Exercise tidak ditemukan di dataset.",
            details={"exercise_id": exercise_id},
        )

    return (
        plan_id,
        plan_exercise_id,
        workout_session_id,
        exercise.exercise_id,
        exercise.exercise_name,
    )


def submit_safety_report(
    session: Session,
    *,
    reporter_user_id: uuid.UUID,
    payload: UnsafeReportCreate,
    dataset: Dataset,
    actor_role: str,
    limit_per_hour: int,
    webhook_url: Optional[str],
) -> UnsafeReport:
    (
        plan_id,
        plan_exercise_id,
        workout_session_id,
        exercise_id,
        exercise_name,
    ) = _resolve_report_context(
        session,
        reporter_user_id=reporter_user_id,
        payload=payload,
        dataset=dataset,
    )
    _check_rate_limit(
        session,
        model=UnsafeReport,
        owner_field=UnsafeReport.reporter_user_id,
        owner_id=reporter_user_id,
        limit=limit_per_hour,
    )

    severity = (
        payload.severity.value
        if isinstance(payload.severity, SafetySeverity)
        else str(payload.severity)
    )
    report = UnsafeReport(
        reporter_user_id=reporter_user_id,
        plan_id=plan_id,
        plan_exercise_id=plan_exercise_id,
        workout_session_id=workout_session_id,
        exercise_id=exercise_id,
        exercise_name=exercise_name,
        reason=payload.reason,
        severity=severity,
        status=SafetyStatus.OPEN.value,
    )
    session.add(report)
    session.flush()

    record_audit(
        session,
        actor_user_id=reporter_user_id,
        actor_role=actor_role,
        action="safety_report.created",
        resource_type="unsafe_report",
        resource_id=str(report.id),
        metadata={
            "exercise_id": exercise_id,
            "severity": report.severity,
            "status": report.status,
        },
    )
    commit_or_conflict(session)

    if report.severity == SafetySeverity.CRITICAL.value:
        send_critical_alert(report, webhook_url)
    return report


def serialize_report(report: UnsafeReport) -> UnsafeReportOut:
    return UnsafeReportOut(
        id=report.id,
        reporter_user_id=report.reporter_user_id,
        plan_id=report.plan_id,
        plan_exercise_id=report.plan_exercise_id,
        workout_session_id=report.workout_session_id,
        exercise_id=report.exercise_id,
        exercise_name=report.exercise_name,
        reason=report.reason,
        severity=report.severity,
        status=report.status,
        resolution_note=report.resolution_note,
        resolved_by=report.resolved_by,
        triaged_at=report.triaged_at,
        resolved_at=report.resolved_at,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


def _validate_filter(value: Optional[str], allowed: Sequence[str], field: str) -> None:
    if value is not None and value not in allowed:
        raise SafetyReportValidationError(
            f"{field} tidak valid.",
            details={"field": field, "value": value},
        )


def list_safety_reports(
    session: Session,
    *,
    status_filter: Optional[str],
    severity_filter: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> Tuple[List[UnsafeReport], Optional[str]]:
    _validate_filter(status_filter, STATUS_VALUES, "status")
    _validate_filter(severity_filter, SEVERITY_VALUES, "severity")
    limit = min(max(limit, 1), 100)

    stmt = select(UnsafeReport).order_by(
        UnsafeReport.created_at.desc(),
        UnsafeReport.id.desc(),
    )
    if status_filter:
        stmt = stmt.where(UnsafeReport.status == status_filter)
    if severity_filter:
        stmt = stmt.where(UnsafeReport.severity == severity_filter)

    if cursor:
        try:
            cursor_id = uuid.UUID(cursor)
        except ValueError as exc:
            raise SafetyReportValidationError("Cursor report tidak valid.") from exc
        cursor_report = session.get(UnsafeReport, cursor_id)
        if cursor_report is None:
            raise SafetyReportValidationError("Cursor report tidak valid.")
        stmt = stmt.where(
            (UnsafeReport.created_at < cursor_report.created_at)
            | (
                (UnsafeReport.created_at == cursor_report.created_at)
                & (UnsafeReport.id < cursor_report.id)
            )
        )

    reports = list(session.scalars(stmt.limit(limit + 1)).all())
    next_cursor = str(reports[limit - 1].id) if len(reports) > limit else None
    return reports[:limit], next_cursor


def update_safety_report(
    session: Session,
    *,
    report_id: uuid.UUID,
    payload: UnsafeReportUpdate,
    admin_user_id: uuid.UUID,
    actor_role: str,
    webhook_url: Optional[str],
) -> UnsafeReport:
    report = session.get(UnsafeReport, report_id)
    if report is None:
        raise SafetyReportNotFoundError()

    old_status = SafetyStatus(report.status)
    old_severity = report.severity
    changed_status = False
    changed_severity = False
    changed_note = False
    now = utcnow()

    if payload.severity is not None:
        new_severity = (
            payload.severity.value
            if isinstance(payload.severity, SafetySeverity)
            else str(payload.severity)
        )
        if new_severity != report.severity:
            report.severity = new_severity
            changed_severity = True

    if payload.status is not None:
        target = SafetyStatus(payload.status)
        if target is not old_status:
            if target not in SAFETY_TRANSITIONS[old_status]:
                raise SafetyTransitionError(
                    "Status safety report tidak bisa berpindah ke target tersebut.",
                    details={"from": old_status.value, "to": target.value},
                )
            report.status = target.value
            changed_status = True
            if target is SafetyStatus.TRIAGED:
                report.triaged_at = report.triaged_at or now
            elif target in {SafetyStatus.RESOLVED, SafetyStatus.DISMISSED}:
                report.triaged_at = report.triaged_at or now
                report.resolved_at = now
                report.resolved_by = admin_user_id

    if (
        payload.resolution_note is not None
        and payload.resolution_note != report.resolution_note
    ):
        report.resolution_note = payload.resolution_note
        changed_note = True

    report.updated_at = now

    if changed_note:
        record_audit(
            session,
            actor_user_id=admin_user_id,
            actor_role=actor_role,
            action="safety_report.note_updated",
            resource_type="unsafe_report",
            resource_id=str(report.id),
            metadata={"field": "resolution_note"},
        )

    if changed_severity:
        record_audit(
            session,
            actor_user_id=admin_user_id,
            actor_role=actor_role,
            action="safety_report.severity_changed",
            resource_type="unsafe_report",
            resource_id=str(report.id),
            metadata={"from": old_severity, "to": report.severity},
        )
    if changed_status:
        action = {
            SafetyStatus.TRIAGED: "safety_report.triaged",
            SafetyStatus.RESOLVED: "safety_report.resolved",
            SafetyStatus.DISMISSED: "safety_report.dismissed",
        }.get(SafetyStatus(report.status), "safety_report.updated")
        record_audit(
            session,
            actor_user_id=admin_user_id,
            actor_role=actor_role,
            action=action,
            resource_type="unsafe_report",
            resource_id=str(report.id),
            metadata={
                "from": old_status.value,
                "to": report.status,
                "severity": report.severity,
            },
        )

    commit_or_conflict(session)
    if (
        report.severity == SafetySeverity.CRITICAL.value
        and old_severity != SafetySeverity.CRITICAL.value
    ):
        send_critical_alert(report, webhook_url)
    return report


def list_feedback(
    session: Session,
    *,
    plan_id: Optional[uuid.UUID],
    limit: int,
    cursor: Optional[str],
) -> Tuple[List[Feedback], Optional[str]]:
    limit = min(max(limit, 1), 100)
    stmt = select(Feedback).order_by(
        Feedback.created_at.desc(),
        Feedback.id.desc(),
    )
    if plan_id is not None:
        stmt = stmt.where(Feedback.plan_id == plan_id)

    if cursor:
        try:
            cursor_id = uuid.UUID(cursor)
        except ValueError as exc:
            raise FeedbackValidationError("Cursor feedback tidak valid.") from exc
        cursor_feedback = session.get(Feedback, cursor_id)
        if cursor_feedback is None:
            raise FeedbackValidationError("Cursor feedback tidak valid.")
        stmt = stmt.where(
            (Feedback.created_at < cursor_feedback.created_at)
            | (
                (Feedback.created_at == cursor_feedback.created_at)
                & (Feedback.id < cursor_feedback.id)
            )
        )

    feedback = list(session.scalars(stmt.limit(limit + 1)).all())
    next_cursor = str(feedback[limit - 1].id) if len(feedback) > limit else None
    return feedback[:limit], next_cursor


def serialize_audit(entry: AuditLog) -> AuditLogOut:
    return AuditLogOut(
        id=entry.id,
        actor_user_id=entry.actor_user_id,
        actor_role=entry.actor_role,
        action=entry.action,
        resource_type=entry.resource_type,
        resource_id=entry.resource_id,
        metadata=dict(entry.metadata_json or {}),
        created_at=entry.created_at,
    )


def list_audit(
    session: Session,
    *,
    action: Optional[str],
    actor_user_id: Optional[uuid.UUID],
    resource_type: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> Tuple[List[AuditLog], Optional[str]]:
    limit = min(max(limit, 1), 100)
    stmt = select(AuditLog).order_by(
        AuditLog.created_at.desc(),
        AuditLog.id.desc(),
    )
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_user_id:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)

    if cursor:
        try:
            cursor_id = uuid.UUID(cursor)
        except ValueError as exc:
            raise FeedbackValidationError("Cursor audit tidak valid.") from exc
        cursor_entry = session.get(AuditLog, cursor_id)
        if cursor_entry is None:
            raise FeedbackValidationError("Cursor audit tidak valid.")
        stmt = stmt.where(
            (AuditLog.created_at < cursor_entry.created_at)
            | (
                (AuditLog.created_at == cursor_entry.created_at)
                & (AuditLog.id < cursor_entry.id)
            )
        )

    entries = list(session.scalars(stmt.limit(limit + 1)).all())
    next_cursor = str(entries[limit - 1].id) if len(entries) > limit else None
    return entries[:limit], next_cursor


def quality_summary(session: Session) -> QualitySummary:
    total_plans = int(
        session.scalar(
            select(func.count(Plan.id)).where(Plan.deleted_at.is_(None))
        )
        or 0
    )
    total_feedback = int(
        session.scalar(select(func.count(Feedback.id))) or 0
    )
    average_rating_value = session.scalar(select(func.avg(Feedback.rating)))
    average_rating = (
        round(float(average_rating_value), 2)
        if average_rating_value is not None
        else None
    )

    status_rows = session.execute(
        select(UnsafeReport.status, func.count(UnsafeReport.id)).group_by(
            UnsafeReport.status
        )
    ).all()
    severity_rows = session.execute(
        select(UnsafeReport.severity, func.count(UnsafeReport.id)).group_by(
            UnsafeReport.severity
        )
    ).all()

    reports_by_status = dict.fromkeys(STATUS_VALUES, 0)
    reports_by_status.update({status: int(count) for status, count in status_rows})
    reports_by_severity = dict.fromkeys(SEVERITY_VALUES, 0)
    reports_by_severity.update(
        {severity: int(count) for severity, count in severity_rows}
    )
    reports_total = sum(reports_by_status.values())

    resolution_hours: List[float] = []
    resolved_reports = session.scalars(
        select(UnsafeReport).where(UnsafeReport.resolved_at.is_not(None))
    ).all()
    for report in resolved_reports:
        if report.resolved_at is None:
            continue
        resolution_hours.append(
            max(
                0.0,
                (_as_utc(report.resolved_at) - _as_utc(report.created_at)).total_seconds()
                / 3600,
            )
        )

    return QualitySummary(
        total_plans=total_plans,
        total_feedback=total_feedback,
        average_rating=average_rating,
        reports_total=reports_total,
        reports_by_status=reports_by_status,
        reports_by_severity=reports_by_severity,
        reports_per_1000_plans=(
            round(reports_total / total_plans * 1000, 2) if total_plans else None
        ),
        median_resolution_hours=(
            round(float(statistics.median(resolution_hours)), 2)
            if resolution_hours
            else None
        ),
    )


def _post_alert(url: str, payload: Dict[str, Any]) -> None:
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5):
            return
    except Exception:
        logger.warning("critical_safety_alert_failed", exc_info=True)


def send_critical_alert(report: UnsafeReport, webhook_url: Optional[str]) -> None:
    if not webhook_url:
        logger.warning(
            "critical_safety_report",
            extra={"report_id": str(report.id), "exercise_id": report.exercise_id},
        )
        return

    payload = {
        "text": f"Critical safety report: {report.exercise_id} ({report.id})",
        "report_id": str(report.id),
        "exercise_id": report.exercise_id,
        "severity": report.severity,
        "status": report.status,
    }
    threading.Thread(
        target=_post_alert,
        args=(webhook_url, payload),
        daemon=True,
    ).start()
