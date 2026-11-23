"""P2.2 research events, experiments, versions, quality reviews, and export."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Mapping, Optional, Tuple

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import (
    ExperimentConflictError,
    ExperimentNotFoundError,
    QualityReviewNotFoundError,
    QualityReviewValidationError,
    RateLimitExceededError,
    ResearchConsentRequiredError,
    ResearchEventInvalidError,
    ResearchExportNotConfiguredError,
    ResearchRangeInvalidError,
)
from app.db.models import (
    Consent,
    Experiment,
    ExperimentAssignment,
    Feedback,
    Plan,
    PlanVersion,
    QualityReview,
    ResearchEvent,
    ResearchVersion,
    UnsafeReport,
    User,
    WorkoutSession,
)
from app.domain.profile import ConsentKind
from app.domain.research import (
    ExperimentStatus,
    QualitySubjectType,
    VersionKind,
    is_sensitive_property_key,
    validate_event_properties,
)
from app.schemas.research import (
    AssignmentOut,
    EventCreate,
    EventOut,
    ExperimentCreate,
    ExperimentOut,
    ExperimentReportOut,
    ExperimentUpdate,
    ExportEventOut,
    ExportFeedbackOut,
    ExportPlanOut,
    ExportSafetyReportOut,
    ExportWorkoutOut,
    QualityReviewCreate,
    QualityReviewOut,
    QualityReviewUpdate,
    ResearchExportOut,
    ResearchReportOut,
    VariantReportOut,
    VersionOut,
)
from app.services.audit import record_audit
from app.services.dataset import Dataset
from app.services.identity import (
    commit_or_conflict,
    has_active_consent,
)

MAX_REPORT_RANGE_DAYS = 366
EXPORT_LIMITS = {
    "events": 2000,
    "plans": 1000,
    "workouts": 1000,
    "feedback": 500,
    "safety_reports": 200,
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _require_consent(session: Session, user_id: uuid.UUID) -> None:
    if not has_active_consent(
        session, user_id, ConsentKind.RESEARCH_ANALYTICS
    ):
        raise ResearchConsentRequiredError()


def _active_research_user_ids(session: Session) -> set[uuid.UUID]:
    rows = session.execute(
        select(Consent, User)
        .join(User, User.id == Consent.user_id)
        .where(
            Consent.kind == ConsentKind.RESEARCH_ANALYTICS.value,
            User.deleted_at.is_(None),
        )
        .order_by(Consent.granted_at.desc(), Consent.created_at.desc())
    ).all()
    latest: Dict[uuid.UUID, Consent] = {}
    for consent, _ in rows:
        latest.setdefault(consent.user_id, consent)
    return {
        user_id
        for user_id, consent in latest.items()
        if consent.revoked_at is None
    }


def _validate_range(start: datetime, end: datetime) -> Tuple[datetime, datetime]:
    start_utc = _as_utc(start)
    end_utc = _as_utc(end)
    if start_utc >= end_utc:
        raise ResearchRangeInvalidError("start harus lebih awal dari end.")
    if end_utc - start_utc > timedelta(days=MAX_REPORT_RANGE_DAYS):
        raise ResearchRangeInvalidError(
            f"Rentang maksimal {MAX_REPORT_RANGE_DAYS} hari."
        )
    return start_utc, end_utc


def submit_event(
    session: Session,
    *,
    user_id: uuid.UUID,
    payload: EventCreate,
    actor_role: str,
    limit_per_hour: int,
) -> Tuple[ResearchEvent, bool]:
    _require_consent(session, user_id)

    if payload.idempotency_key:
        existing = session.scalar(
            select(ResearchEvent).where(
                ResearchEvent.owner_user_id == user_id,
                ResearchEvent.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is not None:
            return existing, False

    now = utcnow()
    recent = int(
        session.scalar(
            select(func.count(ResearchEvent.id)).where(
                ResearchEvent.owner_user_id == user_id,
                ResearchEvent.received_at >= now - timedelta(hours=1),
            )
        )
        or 0
    )
    if recent >= limit_per_hour:
        raise RateLimitExceededError(
            "Batas event research per jam tercapai."
        )

    event = ResearchEvent(
        owner_user_id=user_id,
        name=payload.name,
        properties=dict(payload.properties),
        occurred_at=payload.occurred_at or now,
        received_at=now,
        idempotency_key=payload.idempotency_key,
    )
    session.add(event)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if payload.idempotency_key:
            existing = session.scalar(
                select(ResearchEvent).where(
                    ResearchEvent.owner_user_id == user_id,
                    ResearchEvent.idempotency_key == payload.idempotency_key,
                )
            )
            if existing is not None:
                return existing, False
        raise ResearchEventInvalidError(
            "Event research tidak bisa disimpan. Coba lagi."
        ) from exc
    session.refresh(event)
    return event, True


def serialize_event(event: ResearchEvent) -> EventOut:
    return EventOut(
        id=event.id,
        name=event.name,
        properties=dict(event.properties or {}),
        occurred_at=event.occurred_at,
        received_at=event.received_at,
    )


def _variant_dicts(experiment: Experiment) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for item in experiment.variants or []:
        if not isinstance(item, Mapping):
            continue
        key = item.get("key")
        weight = item.get("weight", 1)
        if not isinstance(key, str) or not key:
            continue
        try:
            numeric_weight = int(weight)
        except (TypeError, ValueError):
            numeric_weight = 1
        result.append({"key": key, "weight": max(1, numeric_weight)})
    return result


def serialize_experiment(experiment: Experiment) -> ExperimentOut:
    return ExperimentOut(
        id=experiment.id,
        key=experiment.key,
        name=experiment.name,
        description=experiment.description,
        status=experiment.status,
        variants=_variant_dicts(experiment),
        traffic_percent=experiment.traffic_percent,
        started_at=experiment.started_at,
        ended_at=experiment.ended_at,
        created_at=experiment.created_at,
        updated_at=experiment.updated_at,
    )


def create_experiment(
    session: Session,
    *,
    payload: ExperimentCreate,
    user_id: uuid.UUID,
    actor_role: str,
) -> Experiment:
    existing = session.scalar(
        select(Experiment.id).where(Experiment.key == payload.key)
    )
    if existing is not None:
        raise ExperimentConflictError("Key eksperimen sudah digunakan.")
    now = utcnow()
    experiment = Experiment(
        key=payload.key,
        name=payload.name,
        description=payload.description,
        status=payload.status.value,
        variants=[
            {"key": variant.key, "weight": variant.weight}
            for variant in payload.variants
        ],
        traffic_percent=payload.traffic_percent,
        created_by=user_id,
        started_at=now if payload.status is ExperimentStatus.RUNNING else None,
    )
    session.add(experiment)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ExperimentConflictError("Key eksperimen sudah digunakan.") from exc
    record_audit(
        session,
        actor_user_id=user_id,
        actor_role=actor_role,
        action="research.experiment_created",
        resource_type="experiment",
        resource_id=str(experiment.id),
        metadata={
            "key": experiment.key,
            "status": experiment.status,
            "traffic_percent": experiment.traffic_percent,
            "variants": [variant["key"] for variant in _variant_dicts(experiment)],
        },
    )
    commit_or_conflict(session)
    return experiment


def list_experiments(
    session: Session,
    *,
    status_filter: Optional[str] = None,
) -> List[ExperimentOut]:
    stmt = select(Experiment).order_by(Experiment.created_at.desc())
    if status_filter:
        stmt = stmt.where(Experiment.status == status_filter)
    return [serialize_experiment(item) for item in session.scalars(stmt).all()]


def get_experiment(session: Session, experiment_id: uuid.UUID) -> Experiment:
    experiment = session.get(Experiment, experiment_id)
    if experiment is None:
        raise ExperimentNotFoundError()
    return experiment


def update_experiment(
    session: Session,
    *,
    experiment_id: uuid.UUID,
    payload: ExperimentUpdate,
    user_id: uuid.UUID,
    actor_role: str,
) -> Experiment:
    experiment = get_experiment(session, experiment_id)
    data = payload.model_dump(exclude_unset=True)
    now = utcnow()
    if "variants" in data and payload.variants is not None:
        experiment.variants = [
            {"key": variant.key, "weight": variant.weight}
            for variant in payload.variants
        ]
    if "traffic_percent" in data and payload.traffic_percent is not None:
        experiment.traffic_percent = payload.traffic_percent
    if "description" in data:
        experiment.description = payload.description
    if payload.status is not None:
        experiment.status = payload.status.value
        if payload.status is ExperimentStatus.RUNNING:
            experiment.started_at = experiment.started_at or now
            experiment.ended_at = None
        elif payload.status is ExperimentStatus.COMPLETED:
            experiment.ended_at = experiment.ended_at or now
        else:
            experiment.ended_at = None
    experiment.updated_at = now
    session.flush()
    record_audit(
        session,
        actor_user_id=user_id,
        actor_role=actor_role,
        action="research.experiment_updated",
        resource_type="experiment",
        resource_id=str(experiment.id),
        metadata={
            "key": experiment.key,
            "fields": sorted(
                field
                for field in ("description", "status", "variants", "traffic_percent")
                if field in data
            ),
        },
    )
    commit_or_conflict(session)
    return experiment


def _bucket(experiment: Experiment, user_id: uuid.UUID) -> Tuple[int, int]:
    digest = hashlib.sha256(
        f"{experiment.key}:{user_id}".encode()
    ).hexdigest()
    return int(digest[:8], 16) % 10000, int(digest[8:16], 16)


def _choose_variant(experiment: Experiment, user_id: uuid.UUID) -> Optional[str]:
    variants = _variant_dicts(experiment)
    if not variants:
        return None
    traffic_bucket, selection = _bucket(experiment, user_id)
    if traffic_bucket >= experiment.traffic_percent * 100:
        return None
    total_weight = sum(variant["weight"] for variant in variants)
    point = selection % total_weight
    cumulative = 0
    for variant in variants:
        cumulative += variant["weight"]
        if point < cumulative:
            return variant["key"]
    return variants[-1]["key"]


def assign_experiments(
    session: Session,
    *,
    user_id: uuid.UUID,
) -> List[AssignmentOut]:
    if not has_active_consent(
        session, user_id, ConsentKind.RESEARCH_ANALYTICS
    ):
        return []

    experiments = list(
        session.scalars(
            select(Experiment)
            .where(Experiment.status == ExperimentStatus.RUNNING.value)
            .order_by(Experiment.key)
        ).all()
    )
    now = utcnow()
    changed = False
    results: List[AssignmentOut] = []
    for experiment in experiments:
        assignment = session.scalar(
            select(ExperimentAssignment).where(
                ExperimentAssignment.experiment_id == experiment.id,
                ExperimentAssignment.user_id == user_id,
            )
        )
        if assignment is None:
            variant = _choose_variant(experiment, user_id)
            if variant is None:
                continue
            assignment = ExperimentAssignment(
                experiment_id=experiment.id,
                user_id=user_id,
                variant=variant,
                assigned_at=now,
            )
            try:
                with session.begin_nested():
                    session.add(assignment)
                    session.flush()
                changed = True
            except IntegrityError:
                assignment = session.scalar(
                    select(ExperimentAssignment).where(
                        ExperimentAssignment.experiment_id == experiment.id,
                        ExperimentAssignment.user_id == user_id,
                    )
                )
                if assignment is None:
                    continue
        if assignment.exposed_at is None:
            assignment.exposed_at = now
            changed = True
        results.append(
            AssignmentOut(
                experiment_key=experiment.key,
                experiment_name=experiment.name,
                variant=assignment.variant,
                assigned_at=assignment.assigned_at,
                exposed_at=assignment.exposed_at,
            )
        )
    if changed:
        commit_or_conflict(session)
    return results


def experiment_report(
    session: Session,
    *,
    experiment: Experiment,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    user_ids: Optional[set[uuid.UUID]] = None,
) -> ExperimentReportOut:
    assignment_stmt = select(
        ExperimentAssignment.variant,
        func.count(ExperimentAssignment.id),
        func.sum(
            case(
                (ExperimentAssignment.exposed_at.is_not(None), 1),
                else_=0,
            )
        ),
    ).where(ExperimentAssignment.experiment_id == experiment.id)
    if start is not None:
        assignment_stmt = assignment_stmt.where(
            ExperimentAssignment.assigned_at >= start
        )
    if end is not None:
        assignment_stmt = assignment_stmt.where(
            ExperimentAssignment.assigned_at <= end
        )
    if user_ids is not None:
        if not user_ids:
            assignment_stmt = assignment_stmt.where(
                ExperimentAssignment.user_id.in_([])
            )
        else:
            assignment_stmt = assignment_stmt.where(
                ExperimentAssignment.user_id.in_(user_ids)
            )
    assignment_rows = session.execute(
        assignment_stmt.group_by(ExperimentAssignment.variant)
    ).all()

    event_stmt = (
        select(
            ExperimentAssignment.variant,
            ResearchEvent.name,
            func.count(ResearchEvent.id),
        )
        .join(
            ResearchEvent,
            ResearchEvent.owner_user_id == ExperimentAssignment.user_id,
        )
        .where(
            ExperimentAssignment.experiment_id == experiment.id,
            ResearchEvent.occurred_at >= ExperimentAssignment.assigned_at,
        )
    )
    if start is not None:
        event_stmt = event_stmt.where(ResearchEvent.occurred_at >= start)
    if end is not None:
        event_stmt = event_stmt.where(ResearchEvent.occurred_at <= end)
    if user_ids is not None:
        if not user_ids:
            event_stmt = event_stmt.where(ResearchEvent.owner_user_id.in_([]))
        else:
            event_stmt = event_stmt.where(
                ResearchEvent.owner_user_id.in_(user_ids)
            )
    event_rows = session.execute(
        event_stmt.group_by(ExperimentAssignment.variant, ResearchEvent.name)
    ).all()

    variant_dicts = _variant_dicts(experiment)
    configured = [variant["key"] for variant in variant_dicts]
    variant_weights = {
        variant["key"]: variant["weight"] for variant in variant_dicts
    }
    extra = sorted(
        {
            str(row[0])
            for row in assignment_rows
            if str(row[0]) not in configured
        }
        | {
            str(row[0])
            for row in event_rows
            if str(row[0]) not in configured
        }
    )
    variants = configured + extra
    assignments_by_variant = {
        str(variant): int(total or 0)
        for variant, total, _ in assignment_rows
    }
    exposures_by_variant = {
        str(variant): int(exposed or 0)
        for variant, _, exposed in assignment_rows
    }
    events_by_variant: Dict[str, Dict[str, int]] = {
        variant: {} for variant in variants
    }
    for variant, name, total in event_rows:
        events_by_variant.setdefault(str(variant), {})[str(name)] = int(total or 0)

    by_variant = [
        VariantReportOut(
            variant=variant,
            assignments=assignments_by_variant.get(variant, 0),
            exposures=exposures_by_variant.get(variant, 0),
            events=events_by_variant.get(variant, {}),
        )
        for variant in variants
    ]
    return ExperimentReportOut(
        id=experiment.id,
        key=experiment.key,
        name=experiment.name,
        status=experiment.status,
        traffic_percent=experiment.traffic_percent,
        variants=variants,
        variant_weights=variant_weights,
        assignments_total=sum(item.assignments for item in by_variant),
        exposures_total=sum(item.exposures for item in by_variant),
        by_variant=by_variant,
        generated_at=utcnow(),
    )


def _register_version(
    session: Session,
    *,
    kind: VersionKind,
    version: str,
    checksum: str,
    row_count: Optional[int],
    metadata: Dict[str, Any],
    user_id: uuid.UUID,
    actor_role: str,
) -> Tuple[ResearchVersion, bool]:
    existing = session.scalar(
        select(ResearchVersion).where(
            ResearchVersion.kind == kind.value,
            ResearchVersion.version == version,
        )
    )
    if existing is not None:
        return existing, False
    record = ResearchVersion(
        kind=kind.value,
        version=version,
        checksum=checksum,
        row_count=row_count,
        metadata_json=metadata,
    )
    session.add(record)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        existing = session.scalar(
            select(ResearchVersion).where(
                ResearchVersion.kind == kind.value,
                ResearchVersion.version == version,
            )
        )
        if existing is not None:
            return existing, False
        raise ExperimentConflictError(
            "Versi research gagal didaftarkan."
        ) from exc
    record_audit(
        session,
        actor_user_id=user_id,
        actor_role=actor_role,
        action="research.version_registered",
        resource_type="research_version",
        resource_id=str(record.id),
        metadata={"kind": record.kind, "version": record.version},
    )
    return record, True


def register_versions(
    session: Session,
    *,
    dataset: Dataset,
    settings: Settings,
    user_id: uuid.UUID,
    actor_role: str,
) -> List[ResearchVersion]:
    dataset_checksum = hashlib.sha256(
        dataset.version.encode("utf-8")
    ).hexdigest()
    algorithm_checksum = hashlib.sha256(
        settings.app_version.encode("utf-8")
    ).hexdigest()
    dataset_record, dataset_created = _register_version(
        session,
        kind=VersionKind.DATASET,
        version=dataset.version,
        checksum=dataset_checksum,
        row_count=len(dataset.exercises),
        metadata={
            "exercise_count": len(dataset.exercises),
            "app_version": settings.app_version,
        },
        user_id=user_id,
        actor_role=actor_role,
    )
    algorithm_record, algorithm_created = _register_version(
        session,
        kind=VersionKind.ALGORITHM,
        version=settings.app_version,
        checksum=algorithm_checksum,
        row_count=None,
        metadata={
            "dataset_version": dataset.version,
            "ga_num_generations": settings.ga_num_generations,
            "ga_sol_per_pop": settings.ga_sol_per_pop,
            "ga_num_parents_mating": settings.ga_num_parents_mating,
            "ga_mutation_percent_genes": settings.ga_mutation_percent_genes,
            "ga_stop_criteria": settings.ga_stop_criteria,
        },
        user_id=user_id,
        actor_role=actor_role,
    )
    if dataset_created or algorithm_created:
        commit_or_conflict(session)
    return [dataset_record, algorithm_record]


def serialize_version(record: ResearchVersion) -> VersionOut:
    return VersionOut(
        id=record.id,
        kind=record.kind,
        version=record.version,
        checksum=record.checksum,
        row_count=record.row_count,
        metadata=dict(record.metadata_json or {}),
        created_at=record.created_at,
    )


def list_versions(
    session: Session,
    *,
    kind: Optional[str] = None,
) -> List[VersionOut]:
    stmt = select(ResearchVersion).order_by(
        ResearchVersion.kind, ResearchVersion.created_at.desc()
    )
    if kind:
        stmt = stmt.where(ResearchVersion.kind == kind)
    return [serialize_version(item) for item in session.scalars(stmt).all()]


def _validate_quality_subject(
    session: Session,
    *,
    subject_type: QualitySubjectType,
    subject_id: str,
) -> None:
    if subject_type is QualitySubjectType.PLAN_VERSION:
        try:
            plan_version_id = uuid.UUID(subject_id)
        except ValueError as exc:
            raise QualityReviewValidationError(
                "subject_id plan_version harus UUID."
            ) from exc
        if session.get(PlanVersion, plan_version_id) is None:
            raise QualityReviewValidationError("Plan version tidak ditemukan.")
        return
    kind = (
        VersionKind.DATASET
        if subject_type is QualitySubjectType.DATASET_VERSION
        else VersionKind.ALGORITHM
    )
    exists = session.scalar(
        select(ResearchVersion.id).where(
            ResearchVersion.kind == kind.value,
            ResearchVersion.version == subject_id,
        )
    )
    if exists is None:
        raise QualityReviewValidationError(
            "Versi belum terdaftar di research registry."
        )


def serialize_quality_review(review: QualityReview) -> QualityReviewOut:
    return QualityReviewOut(
        id=review.id,
        reviewer_user_id=review.reviewer_user_id,
        subject_type=review.subject_type,
        subject_id=review.subject_id,
        status=review.status,
        rubric={str(key): int(value) for key, value in (review.rubric or {}).items()},
        notes=review.notes,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


def create_quality_review(
    session: Session,
    *,
    payload: QualityReviewCreate,
    reviewer_user_id: uuid.UUID,
    actor_role: str,
) -> QualityReview:
    _validate_quality_subject(
        session,
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
    )
    review = QualityReview(
        reviewer_user_id=reviewer_user_id,
        subject_type=payload.subject_type.value,
        subject_id=payload.subject_id,
        status=payload.status.value,
        rubric=dict(payload.rubric),
        notes=payload.notes,
    )
    session.add(review)
    session.flush()
    record_audit(
        session,
        actor_user_id=reviewer_user_id,
        actor_role=actor_role,
        action="research.quality_review_created",
        resource_type="quality_review",
        resource_id=str(review.id),
        metadata={
            "subject_type": review.subject_type,
            "subject_id": review.subject_id,
            "status": review.status,
        },
    )
    commit_or_conflict(session)
    return review


def list_quality_reviews(
    session: Session,
    *,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 100,
) -> List[QualityReviewOut]:
    stmt = select(QualityReview).order_by(QualityReview.created_at.desc())
    if subject_type:
        stmt = stmt.where(QualityReview.subject_type == subject_type)
    if subject_id:
        stmt = stmt.where(QualityReview.subject_id == subject_id)
    if status_filter:
        stmt = stmt.where(QualityReview.status == status_filter)
    return [
        serialize_quality_review(item)
        for item in session.scalars(stmt.limit(limit)).all()
    ]


def get_quality_review(
    session: Session, review_id: uuid.UUID
) -> QualityReview:
    review = session.get(QualityReview, review_id)
    if review is None:
        raise QualityReviewNotFoundError()
    return review


def update_quality_review(
    session: Session,
    *,
    review_id: uuid.UUID,
    payload: QualityReviewUpdate,
    reviewer_user_id: uuid.UUID,
    actor_role: str,
) -> QualityReview:
    review = get_quality_review(session, review_id)
    data = payload.model_dump(exclude_unset=True)
    if payload.status is not None:
        review.status = payload.status.value
    if payload.rubric is not None:
        review.rubric = dict(payload.rubric)
    if "notes" in data:
        review.notes = payload.notes
    review.updated_at = utcnow()
    session.flush()
    record_audit(
        session,
        actor_user_id=reviewer_user_id,
        actor_role=actor_role,
        action="research.quality_review_updated",
        resource_type="quality_review",
        resource_id=str(review.id),
        metadata={
            "subject_type": review.subject_type,
            "status": review.status,
            "fields": sorted(
                field for field in ("notes", "rubric", "status") if field in data
            ),
        },
    )
    commit_or_conflict(session)
    return review


def research_report(
    session: Session,
    *,
    start: datetime,
    end: datetime,
) -> ResearchReportOut:
    start_utc, end_utc = _validate_range(start, end)
    consented = _active_research_user_ids(session)
    generated_at = utcnow()

    if consented:
        event_total = int(
            session.scalar(
                select(func.count(ResearchEvent.id)).where(
                    ResearchEvent.owner_user_id.in_(consented),
                    ResearchEvent.occurred_at >= start_utc,
                    ResearchEvent.occurred_at <= end_utc,
                )
            )
            or 0
        )
        unique_event_users = int(
            session.scalar(
                select(func.count(func.distinct(ResearchEvent.owner_user_id))).where(
                    ResearchEvent.owner_user_id.in_(consented),
                    ResearchEvent.occurred_at >= start_utc,
                    ResearchEvent.occurred_at <= end_utc,
                )
            )
            or 0
        )
        event_rows = session.execute(
            select(ResearchEvent.name, func.count(ResearchEvent.id))
            .where(
                ResearchEvent.owner_user_id.in_(consented),
                ResearchEvent.occurred_at >= start_utc,
                ResearchEvent.occurred_at <= end_utc,
            )
            .group_by(ResearchEvent.name)
        ).all()

        plans_total = int(
            session.scalar(
                select(func.count(Plan.id)).where(
                    Plan.owner_user_id.in_(consented),
                    Plan.deleted_at.is_(None),
                    Plan.created_at >= start_utc,
                    Plan.created_at <= end_utc,
                )
            )
            or 0
        )
        plans_by_dataset = session.execute(
            select(Plan.dataset_version, func.count(Plan.id))
            .where(
                Plan.owner_user_id.in_(consented),
                Plan.deleted_at.is_(None),
                Plan.created_at >= start_utc,
                Plan.created_at <= end_utc,
            )
            .group_by(Plan.dataset_version)
        ).all()
        plans_by_algorithm = session.execute(
            select(Plan.algorithm_version, func.count(Plan.id))
            .where(
                Plan.owner_user_id.in_(consented),
                Plan.deleted_at.is_(None),
                Plan.created_at >= start_utc,
                Plan.created_at <= end_utc,
            )
            .group_by(Plan.algorithm_version)
        ).all()

        workouts_total = int(
            session.scalar(
                select(func.count(WorkoutSession.id)).where(
                    WorkoutSession.owner_user_id.in_(consented),
                    WorkoutSession.started_at >= start_utc,
                    WorkoutSession.started_at <= end_utc,
                )
            )
            or 0
        )
        workouts_completed = int(
            session.scalar(
                select(func.count(WorkoutSession.id)).where(
                    WorkoutSession.owner_user_id.in_(consented),
                    WorkoutSession.status == "completed",
                    WorkoutSession.started_at >= start_utc,
                    WorkoutSession.started_at <= end_utc,
                )
            )
            or 0
        )

        feedback_total = int(
            session.scalar(
                select(func.count(Feedback.id)).where(
                    Feedback.owner_user_id.in_(consented),
                    Feedback.created_at >= start_utc,
                    Feedback.created_at <= end_utc,
                )
            )
            or 0
        )
        average_rating_value = session.scalar(
            select(func.avg(Feedback.rating)).where(
                Feedback.owner_user_id.in_(consented),
                Feedback.rating.is_not(None),
                Feedback.created_at >= start_utc,
                Feedback.created_at <= end_utc,
            )
        )

        safety_total = int(
            session.scalar(
                select(func.count(UnsafeReport.id)).where(
                    UnsafeReport.reporter_user_id.in_(consented),
                    UnsafeReport.created_at >= start_utc,
                    UnsafeReport.created_at <= end_utc,
                )
            )
            or 0
        )
        severity_rows = session.execute(
            select(UnsafeReport.severity, func.count(UnsafeReport.id))
            .where(
                UnsafeReport.reporter_user_id.in_(consented),
                UnsafeReport.created_at >= start_utc,
                UnsafeReport.created_at <= end_utc,
            )
            .group_by(UnsafeReport.severity)
        ).all()
        status_rows = session.execute(
            select(UnsafeReport.status, func.count(UnsafeReport.id))
            .where(
                UnsafeReport.reporter_user_id.in_(consented),
                UnsafeReport.created_at >= start_utc,
                UnsafeReport.created_at <= end_utc,
            )
            .group_by(UnsafeReport.status)
        ).all()
    else:
        event_total = 0
        unique_event_users = 0
        event_rows = []
        plans_total = 0
        plans_by_dataset = []
        plans_by_algorithm = []
        workouts_total = 0
        workouts_completed = 0
        feedback_total = 0
        average_rating_value = None
        safety_total = 0
        severity_rows = []
        status_rows = []

    experiments = list(
        session.scalars(select(Experiment).order_by(Experiment.key)).all()
    )
    experiment_reports = [
        experiment_report(
            session,
            experiment=experiment,
            start=start_utc,
            end=end_utc,
            user_ids=consented,
        )
        for experiment in experiments
        if experiment.status != ExperimentStatus.DRAFT.value
    ]

    return ResearchReportOut(
        start=start_utc,
        end=end_utc,
        generated_at=generated_at,
        versions=list_versions(session),
        events_total=event_total,
        unique_event_users=unique_event_users,
        events_by_name={str(name): int(total) for name, total in event_rows},
        plans_total=plans_total,
        plans_by_dataset_version={
            str(version): int(total) for version, total in plans_by_dataset
        },
        plans_by_algorithm_version={
            str(version): int(total) for version, total in plans_by_algorithm
        },
        workouts_total=workouts_total,
        workouts_completed=workouts_completed,
        workout_completion_rate=(
            round(workouts_completed / workouts_total * 100, 2)
            if workouts_total
            else None
        ),
        feedback_total=feedback_total,
        average_rating=(
            round(float(average_rating_value), 2)
            if average_rating_value is not None
            else None
        ),
        safety_reports_total=safety_total,
        reports_by_severity={
            str(severity): int(total) for severity, total in severity_rows
        },
        reports_by_status={
            str(status): int(total) for status, total in status_rows
        },
        experiments=experiment_reports,
    )


def _pseudonym(secret: str, prefix: str, value: object) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{prefix}:{value}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{prefix}_{digest[:16]}"


def _safe_properties(properties: Mapping[str, Any]) -> Dict[str, Any]:
    try:
        return validate_event_properties(properties)
    except ValueError:
        return {
            key: value
            for key, value in properties.items()
            if not is_sensitive_property_key(str(key))
            and isinstance(value, (str, int, float, bool))
        }


def research_export(
    session: Session,
    *,
    start: datetime,
    end: datetime,
    secret: Optional[str],
    actor_user_id: uuid.UUID,
    actor_role: str,
) -> ResearchExportOut:
    start_utc, end_utc = _validate_range(start, end)
    if not secret or len(secret) < 32:
        raise ResearchExportNotConfiguredError()
    consented = _active_research_user_ids(session)
    generated_at = utcnow()

    def user_ref(user_id: uuid.UUID) -> str:
        return _pseudonym(secret, "user", user_id)

    def plan_ref(plan_id: uuid.UUID) -> str:
        return _pseudonym(secret, "plan", plan_id)

    def workout_ref(workout_id: uuid.UUID) -> str:
        return _pseudonym(secret, "workout", workout_id)

    events: List[ExportEventOut] = []
    plans: List[ExportPlanOut] = []
    workouts: List[ExportWorkoutOut] = []
    feedback_rows: List[ExportFeedbackOut] = []
    reports: List[ExportSafetyReportOut] = []
    raw_counts = dict.fromkeys(EXPORT_LIMITS, 0)

    if consented:
        event_rows = session.scalars(
            select(ResearchEvent)
            .where(
                ResearchEvent.owner_user_id.in_(consented),
                ResearchEvent.occurred_at >= start_utc,
                ResearchEvent.occurred_at <= end_utc,
            )
            .order_by(ResearchEvent.occurred_at)
            .limit(EXPORT_LIMITS["events"] + 1)
        ).all()
        raw_counts["events"] = len(event_rows)
        events = [
            ExportEventOut(
                user_ref=user_ref(row.owner_user_id),
                name=row.name,
                properties=_safe_properties(row.properties or {}),
                occurred_at=row.occurred_at,
            )
            for row in event_rows[: EXPORT_LIMITS["events"]]
        ]

        plan_rows = session.scalars(
            select(Plan)
            .where(
                Plan.owner_user_id.in_(consented),
                Plan.deleted_at.is_(None),
                Plan.created_at >= start_utc,
                Plan.created_at <= end_utc,
            )
            .order_by(Plan.created_at)
            .limit(EXPORT_LIMITS["plans"] + 1)
        ).all()
        raw_counts["plans"] = len(plan_rows)
        plans = [
            ExportPlanOut(
                user_ref=user_ref(row.owner_user_id),
                plan_ref=plan_ref(row.id),
                created_at=row.created_at,
                day_count=row.day_count,
                split_type=row.split_type,
                bmi_category=row.bmi_category,
                dataset_version=row.dataset_version,
                algorithm_version=row.algorithm_version,
            )
            for row in plan_rows[: EXPORT_LIMITS["plans"]]
        ]

        workout_rows = session.scalars(
            select(WorkoutSession)
            .where(
                WorkoutSession.owner_user_id.in_(consented),
                WorkoutSession.started_at >= start_utc,
                WorkoutSession.started_at <= end_utc,
            )
            .order_by(WorkoutSession.started_at)
            .limit(EXPORT_LIMITS["workouts"] + 1)
        ).all()
        raw_counts["workouts"] = len(workout_rows)
        workouts = [
            ExportWorkoutOut(
                user_ref=user_ref(row.owner_user_id),
                workout_ref=workout_ref(row.id),
                plan_ref=plan_ref(row.plan_id) if row.plan_id else None,
                status=row.status,
                started_at=row.started_at,
                completed_at=row.completed_at,
                total_sets=row.total_sets,
            )
            for row in workout_rows[: EXPORT_LIMITS["workouts"]]
        ]

        feedback_query = session.scalars(
            select(Feedback)
            .where(
                Feedback.owner_user_id.in_(consented),
                Feedback.created_at >= start_utc,
                Feedback.created_at <= end_utc,
            )
            .order_by(Feedback.created_at)
            .limit(EXPORT_LIMITS["feedback"] + 1)
        ).all()
        raw_counts["feedback"] = len(feedback_query)
        feedback_rows = [
            ExportFeedbackOut(
                user_ref=user_ref(row.owner_user_id),
                plan_ref=plan_ref(row.plan_id) if row.plan_id else None,
                workout_ref=(
                    workout_ref(row.workout_session_id)
                    if row.workout_session_id
                    else None
                ),
                rating=row.rating,
                difficulty=row.difficulty,
                pain=bool(row.pain),
                created_at=row.created_at,
            )
            for row in feedback_query[: EXPORT_LIMITS["feedback"]]
        ]

        report_rows = session.scalars(
            select(UnsafeReport)
            .where(
                UnsafeReport.reporter_user_id.in_(consented),
                UnsafeReport.created_at >= start_utc,
                UnsafeReport.created_at <= end_utc,
            )
            .order_by(UnsafeReport.created_at)
            .limit(EXPORT_LIMITS["safety_reports"] + 1)
        ).all()
        raw_counts["safety_reports"] = len(report_rows)
        reports = [
            ExportSafetyReportOut(
                user_ref=user_ref(row.reporter_user_id),
                exercise_id=row.exercise_id,
                severity=row.severity,
                status=row.status,
                created_at=row.created_at,
                resolved_at=row.resolved_at,
            )
            for row in report_rows[: EXPORT_LIMITS["safety_reports"]]
            if row.reporter_user_id is not None
        ]

    truncated = {
        key: raw_counts[key] > limit for key, limit in EXPORT_LIMITS.items()
    }
    record_audit(
        session,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action="research.export_generated",
        resource_type="research_export",
        metadata={
            "start": start_utc.isoformat(),
            "end": end_utc.isoformat(),
            "users": len(consented),
            "events": len(events),
            "plans": len(plans),
            "workouts": len(workouts),
            "feedback": len(feedback_rows),
            "safety_reports": len(reports),
        },
    )
    session.commit()

    return ResearchExportOut(
        generated_at=generated_at,
        start=start_utc,
        end=end_utc,
        user_count=len(consented),
        events=events,
        plans=plans,
        workouts=workouts,
        feedback=feedback_rows,
        safety_reports=reports,
        versions=list_versions(session),
        truncated=truncated,
    )
