"""Domain and application errors with stable API error codes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from fastapi import status


class AppError(Exception):
    """Base class for expected application errors."""

    code = "application_error"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    message = "Terjadi kesalahan pada aplikasi."
    headers: Optional[Dict[str, str]] = None

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        details: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details
        self.headers = headers or self.headers


class UnauthorizedError(AppError):
    code = "unauthorized"
    status_code = status.HTTP_401_UNAUTHORIZED
    message = "Token akses tidak valid atau tidak dikirim."


class ForbiddenError(AppError):
    code = "forbidden"
    status_code = status.HTTP_403_FORBIDDEN
    message = "Akses ditolak."


class NotFoundError(AppError):
    code = "not_found"
    status_code = status.HTTP_404_NOT_FOUND
    message = "Resource tidak ditemukan."


class ConflictError(AppError):
    code = "conflict"
    status_code = status.HTTP_409_CONFLICT
    message = "Terjadi konflik data."


class ConsentRequiredError(ConflictError):
    code = "consent_required"
    message = "Persetujuan pemrosesan data kesehatan diperlukan."


class AccountDeletionPendingError(ForbiddenError):
    code = "account_deletion_pending"
    message = "Akun sedang dalam proses penghapusan."


class AuthNotConfiguredError(AppError):
    code = "auth_not_configured"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "Autentikasi belum dikonfigurasi."


class AuthUnavailableError(AppError):
    code = "auth_unavailable"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "Layanan autentikasi sedang tidak tersedia."


class DatabaseNotConfiguredError(AppError):
    code = "database_not_configured"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "Database belum dikonfigurasi."


class InvalidInputError(AppError):
    code = "invalid_input"
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    message = "Input tidak valid."


class PlanNotFoundError(NotFoundError):
    code = "plan_not_found"
    message = "Plan tidak ditemukan."


class ShareNotFoundError(NotFoundError):
    code = "share_not_found"
    message = "Share link tidak ditemukan atau sudah kedaluwarsa."


class PlanRevisionConflictError(ConflictError):
    code = "plan_revision_conflict"
    message = "Plan sudah berubah. Muat ulang plan sebelum mengedit."


class PlanDatasetMismatchError(ConflictError):
    code = "plan_dataset_mismatch"
    message = "Plan dibuat dengan dataset yang berbeda. Buat ulang plan."


class PlanValidationError(InvalidInputError):
    code = "plan_invalid"
    message = "Data plan tidak valid."


class ExerciseLockedError(ConflictError):
    code = "exercise_locked"
    message = "Exercise terkunci. Buka lock sebelum mengganti."


class IdempotencyConflictError(ConflictError):
    code = "idempotency_conflict"
    message = "Idempotency-Key sudah dipakai untuk request yang berbeda."


class PreconditionRequiredError(AppError):
    code = "precondition_required"
    status_code = status.HTTP_428_PRECONDITION_REQUIRED
    message = "expected_revision atau If-Match wajib dikirim."


class InvalidCursorError(InvalidInputError):
    code = "invalid_cursor"
    message = "Cursor pagination tidak valid."


class WorkoutNotFoundError(NotFoundError):
    code = "workout_not_found"
    message = "Workout tidak ditemukan."


class SetNotFoundError(NotFoundError):
    code = "set_not_found"
    message = "Set tidak ditemukan."


class WorkoutValidationError(InvalidInputError):
    code = "workout_invalid"
    message = "Data workout tidak valid."


class WorkoutCompletedError(ConflictError):
    code = "workout_completed"
    message = "Workout sudah selesai dan tidak bisa diubah."


class SetConflictError(ConflictError):
    code = "set_conflict"
    message = "Nomor set sudah dipakai untuk exercise ini."


class FeedbackNotFoundError(NotFoundError):
    code = "feedback_not_found"
    message = "Feedback tidak ditemukan."


class SafetyReportNotFoundError(NotFoundError):
    code = "safety_report_not_found"
    message = "Safety report tidak ditemukan."


class FeedbackValidationError(InvalidInputError):
    code = "feedback_invalid"
    message = "Data feedback tidak valid."


class SafetyReportValidationError(InvalidInputError):
    code = "safety_report_invalid"
    message = "Data safety report tidak valid."


class SafetyTransitionError(ConflictError):
    code = "invalid_safety_transition"
    message = "Transisi status safety report tidak valid."


class RateLimitExceededError(AppError):
    code = "rate_limit_exceeded"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    message = "Terlalu banyak request. Coba lagi nanti."


class ProgressValidationError(InvalidInputError):
    code = "progress_invalid"
    message = "Rentang progress tidak valid."


class TrainerProfileNotFoundError(NotFoundError):
    code = "trainer_profile_not_found"
    message = "Profil trainer tidak ditemukan."


class TrainerInvitationNotFoundError(NotFoundError):
    code = "trainer_invitation_not_found"
    message = "Undangan trainer tidak ditemukan atau sudah kedaluwarsa."


class TrainerInvitationConflictError(ConflictError):
    code = "trainer_invitation_conflict"
    message = "Undangan trainer tidak bisa dibuat atau diproses."


class TrainerAccessDeniedError(ForbiddenError):
    code = "trainer_access_denied"
    message = "Akses ke data client tidak diizinkan."


class TrainerClientNotFoundError(NotFoundError):
    code = "trainer_client_not_found"
    message = "Client tidak ditemukan pada workspace trainer."


class TrainerValidationError(InvalidInputError):
    code = "trainer_invalid"
    message = "Data trainer tidak valid."


class NotificationValidationError(InvalidInputError):
    code = "notification_invalid"
    message = "Preferensi notifikasi tidak valid."


class DeviceNotFoundError(NotFoundError):
    code = "device_not_found"
    message = "Device tidak ditemukan."


class CalendarNotFoundError(NotFoundError):
    code = "calendar_not_found"
    message = "Calendar feed tidak ditemukan."


class IntegrationNotConfiguredError(AppError):
    code = "integration_not_configured"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "Integrasi belum dikonfigurasi."


class IntegrationStateError(ForbiddenError):
    code = "integration_state_invalid"
    message = "State integrasi tidak valid atau kedaluwarsa."


class IntegrationUnsupportedError(InvalidInputError):
    code = "integration_unsupported"
    message = "Provider integrasi tidak didukung."


class IntegrationExchangeError(AppError):
    code = "integration_exchange_failed"
    status_code = status.HTTP_502_BAD_GATEWAY
    message = "Pertukaran token integrasi gagal."


class OrganizationNotFoundError(NotFoundError):
    code = "organization_not_found"
    message = "Organisasi tidak ditemukan."


class OrganizationAccessDeniedError(ForbiddenError):
    code = "organization_access_denied"
    message = "Akses organisasi tidak diizinkan."


class OrganizationInvitationNotFoundError(NotFoundError):
    code = "organization_invitation_not_found"
    message = "Undangan organisasi tidak ditemukan atau kedaluwarsa."


class OrganizationInvitationConflictError(ConflictError):
    code = "organization_invitation_conflict"
    message = "Undangan organisasi tidak bisa diproses."


class OrganizationConflictError(ConflictError):
    code = "organization_conflict"
    message = "Terjadi konflik pada organisasi."


class OrganizationValidationError(InvalidInputError):
    code = "organization_invalid"
    message = "Data organisasi tidak valid."


class ResearchConsentRequiredError(ForbiddenError):
    code = "research_consent_required"
    message = "Persetujuan research analytics diperlukan."


class ResearchEventInvalidError(InvalidInputError):
    code = "research_event_invalid"
    message = "Event research tidak valid."


class ExperimentNotFoundError(NotFoundError):
    code = "experiment_not_found"
    message = "Eksperimen tidak ditemukan."


class ExperimentConflictError(ConflictError):
    code = "experiment_conflict"
    message = "Terjadi konflik pada eksperimen."


class ExperimentValidationError(InvalidInputError):
    code = "experiment_invalid"
    message = "Data eksperimen tidak valid."


class QualityReviewNotFoundError(NotFoundError):
    code = "quality_review_not_found"
    message = "Quality review tidak ditemukan."


class QualityReviewValidationError(InvalidInputError):
    code = "quality_review_invalid"
    message = "Data quality review tidak valid."


class ResearchExportNotConfiguredError(AppError):
    code = "research_export_not_configured"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "Research export belum dikonfigurasi."


class ResearchRangeInvalidError(InvalidInputError):
    code = "research_range_invalid"
    message = "Rentang tanggal research tidak valid."


class ProfileValidationError(InvalidInputError):
    code = "validation_error"
    message = "Data profil tidak valid."


class UnsupportedDaysError(InvalidInputError):
    code = "unsupported_available_days"
    message = "Jumlah hari latihan harus antara 1 dan 5."


class UnknownInjuryError(InvalidInputError):
    code = "unknown_injury"
    message = "Nama cedera tidak dikenali."


class InvalidFocusError(InvalidInputError):
    code = "invalid_focus"
    message = "Fokus latihan tidak valid."


class InsufficientPoolError(AppError):
    code = "insufficient_exercise_pool"
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    message = (
        "Tidak cukup latihan aman untuk menyusun jadwal pada fokus tersebut. "
        "Coba longgarkan preferensi alat atau kurangi area cedera."
    )


class DatasetError(AppError):
    code = "invalid_dataset"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    message = "Dataset latihan tidak valid atau tidak dapat dibaca."


class ServiceUnavailableError(AppError):
    code = "service_unavailable"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "Layanan sedang tidak tersedia."


def error_payload(
    *,
    code: str,
    message: str,
    request_id: str,
    details: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build the public error envelope."""

    error: Dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    # ``detail`` is kept for clients built against the old FastAPI default
    # error shape; new clients should use ``error``.  ``message`` is a flat
    # convenience key used by the current Vue frontend.
    return {
        "error": error,
        "request_id": request_id,
        "detail": message,
        "message": message,
    }


def validation_details(errors: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Trim Pydantic errors to fields that are safe/useful to expose."""

    cleaned: List[Dict[str, Any]] = []
    for item in errors:
        cleaned.append(
            {
                "field": ".".join(str(part) for part in item.get("loc", [])),
                "message": item.get("msg", "invalid value"),
                "type": item.get("type", "value_error"),
            }
        )
    return cleaned
