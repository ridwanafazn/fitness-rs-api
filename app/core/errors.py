"""Domain and application errors with stable API error codes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from fastapi import status


class AppError(Exception):
    """Base class for expected application errors."""

    code = "application_error"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    message = "Terjadi kesalahan pada aplikasi."

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        details: Optional[Any] = None,
    ) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details


class UnauthorizedError(AppError):
    code = "unauthorized"
    status_code = status.HTTP_401_UNAUTHORIZED
    message = "API key tidak valid atau tidak dikirim."


class InvalidInputError(AppError):
    code = "invalid_input"
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    message = "Input tidak valid."


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
    # error shape; new clients should use ``error``.
    return {"error": error, "request_id": request_id, "detail": message}


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
