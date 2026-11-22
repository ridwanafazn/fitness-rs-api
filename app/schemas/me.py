"""Request/response schemas for P0.1 identity and profile endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.domain.constants import Gender
from app.domain.profile import (
    SUPPORTED_LOCALES,
    ConsentKind,
    Experience,
    Goal,
    UnitSystem,
)


def _normalise_enum_value(value: Any, enum_type) -> Any:
    if not isinstance(value, str):
        return value
    token = value.strip().lower().replace("-", "_").replace(" ", "_")
    try:
        return enum_type(token)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ValueError(f"Nilai harus salah satu dari: {allowed}.") from exc


def _normalise_locale(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    key = value.strip().lower().replace("_", "-")
    canonical = SUPPORTED_LOCALES.get(key)
    if canonical is None:
        allowed = ", ".join(sorted(SUPPORTED_LOCALES.values()))
        raise ValueError(f"Locale harus salah satu dari: {allowed}.")
    return canonical


def _validate_timezone(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    timezone = value.strip()
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Timezone harus nama IANA yang valid, misalnya Asia/Jakarta.") from exc
    return timezone


def _normalise_session_minutes(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError("session_minutes harus berupa angka.") from exc
    return value


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    gender: Gender
    height_cm: float = Field(..., gt=50, le=300)
    weight_kg: float = Field(..., gt=10, le=400)
    goal: Goal
    experience: Experience
    session_minutes: Literal[30, 45, 60, 90]
    timezone: str = Field(..., min_length=1, max_length=64)
    locale: str = Field(..., min_length=2, max_length=16)
    unit_system: UnitSystem

    @field_validator("gender", mode="before")
    @classmethod
    def _gender(cls, value: Any) -> Any:
        return _normalise_enum_value(value, Gender)

    @field_validator("goal", mode="before")
    @classmethod
    def _goal(cls, value: Any) -> Any:
        return _normalise_enum_value(value, Goal)

    @field_validator("experience", mode="before")
    @classmethod
    def _experience(cls, value: Any) -> Any:
        return _normalise_enum_value(value, Experience)

    @field_validator("unit_system", mode="before")
    @classmethod
    def _unit_system(cls, value: Any) -> Any:
        return _normalise_enum_value(value, UnitSystem)

    @field_validator("locale", mode="before")
    @classmethod
    def _locale(cls, value: Any) -> Any:
        return _normalise_locale(value)

    @field_validator("timezone", mode="before")
    @classmethod
    def _timezone(cls, value: Any) -> Any:
        return _validate_timezone(value)

    @field_validator("session_minutes", mode="before")
    @classmethod
    def _session_minutes(cls, value: Any) -> Any:
        return _normalise_session_minutes(value)


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    gender: Optional[Gender] = None
    height_cm: Optional[float] = Field(default=None, gt=50, le=300)
    weight_kg: Optional[float] = Field(default=None, gt=10, le=400)
    goal: Optional[Goal] = None
    experience: Optional[Experience] = None
    session_minutes: Optional[Literal[30, 45, 60, 90]] = None
    timezone: Optional[str] = Field(default=None, min_length=1, max_length=64)
    locale: Optional[str] = Field(default=None, min_length=2, max_length=16)
    unit_system: Optional[UnitSystem] = None

    @field_validator("gender", mode="before")
    @classmethod
    def _gender(cls, value: Any) -> Any:
        return None if value is None else _normalise_enum_value(value, Gender)

    @field_validator("goal", mode="before")
    @classmethod
    def _goal(cls, value: Any) -> Any:
        return None if value is None else _normalise_enum_value(value, Goal)

    @field_validator("experience", mode="before")
    @classmethod
    def _experience(cls, value: Any) -> Any:
        return None if value is None else _normalise_enum_value(value, Experience)

    @field_validator("unit_system", mode="before")
    @classmethod
    def _unit_system(cls, value: Any) -> Any:
        return None if value is None else _normalise_enum_value(value, UnitSystem)

    @field_validator("locale", mode="before")
    @classmethod
    def _locale(cls, value: Any) -> Any:
        return None if value is None else _normalise_locale(value)

    @field_validator("timezone", mode="before")
    @classmethod
    def _timezone(cls, value: Any) -> Any:
        return None if value is None else _validate_timezone(value)

    @field_validator("session_minutes", mode="before")
    @classmethod
    def _session_minutes(cls, value: Any) -> Any:
        return None if value is None else _normalise_session_minutes(value)

    @model_validator(mode="after")
    def _require_at_least_one_value(self) -> ProfilePatch:
        if not any(value is not None for value in self.model_dump().values()):
            raise ValueError("Minimal satu field profil harus diisi.")
        return self


class OnboardingRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    display_name: Optional[str] = Field(default=None, max_length=100)
    profile: ProfileIn
    equipment: Optional[List[str]] = Field(default=None, max_length=20)
    injuries: Optional[List[str]] = Field(default=None, max_length=10)
    consents: Dict[ConsentKind, bool] = Field(default_factory=dict)

    @field_validator("display_name", mode="before")
    @classmethod
    def _display_name(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        cleaned = " ".join(value.split())
        return cleaned or None

    @field_validator("equipment", mode="before")
    @classmethod
    def _equipment_list(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("equipment harus berupa list.")
        if not all(isinstance(item, str) for item in value):
            raise ValueError("equipment hanya boleh berisi string.")
        if any(len(item) > 64 for item in value):
            raise ValueError("Nilai equipment terlalu panjang.")
        return value

    @field_validator("injuries", mode="before")
    @classmethod
    def _injury_list(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("injuries harus berupa list.")
        if not all(isinstance(item, str) for item in value):
            raise ValueError("injuries hanya boleh berisi string.")
        if any(len(item) > 60 for item in value):
            raise ValueError("Nilai injuries terlalu panjang.")
        return value


class EquipmentUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    equipment: List[str] = Field(default_factory=list, max_length=20)

    @field_validator("equipment", mode="before")
    @classmethod
    def _equipment_list(cls, value: Any) -> Any:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("equipment harus berupa list.")
        if not all(isinstance(item, str) for item in value):
            raise ValueError("equipment hanya boleh berisi string.")
        if any(len(item) > 64 for item in value):
            raise ValueError("Nilai equipment terlalu panjang.")
        return value


class InjuryUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    injuries: List[str] = Field(default_factory=list, max_length=10)

    @field_validator("injuries", mode="before")
    @classmethod
    def _injury_list(cls, value: Any) -> Any:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("injuries harus berupa list.")
        if not all(isinstance(item, str) for item in value):
            raise ValueError("injuries hanya boleh berisi string.")
        if any(len(item) > 60 for item in value):
            raise ValueError("Nilai injuries terlalu panjang.")
        return value


class ConsentUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: ConsentKind
    granted: bool
    version: Optional[str] = Field(default=None, max_length=32)


class MeUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: Optional[str] = None
    display_name: Optional[str] = None
    roles: List[str] = Field(default_factory=list)
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class MeResponse(BaseModel):
    user: MeUser
    profile_complete: bool
    consents: Dict[str, bool]


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    gender: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    goal: Optional[str] = None
    experience: Optional[str] = None
    session_minutes: Optional[int] = None
    timezone: Optional[str] = None
    locale: Optional[str] = None
    unit_system: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _serialize_timestamps(self, value: datetime) -> datetime:
        return _as_utc(value)


class InjuryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    term: str
    body_parts: List[str]
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class ProfileResponse(BaseModel):
    profile: Optional[ProfileOut] = None
    equipment: List[str] = Field(default_factory=list)
    injuries: List[InjuryOut] = Field(default_factory=list)


class EquipmentResponse(BaseModel):
    equipment: List[str] = Field(default_factory=list)


class InjuryResponse(BaseModel):
    injuries: List[InjuryOut] = Field(default_factory=list)


class ConsentRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    version: str
    granted_at: datetime
    revoked_at: Optional[datetime] = None

    @field_serializer("granted_at", "revoked_at")
    def _serialize_timestamps(self, value: Optional[datetime]) -> Optional[datetime]:
        return None if value is None else _as_utc(value)


class ConsentStateResponse(BaseModel):
    policy_version: str
    active: Dict[str, bool]
    records: List[ConsentRecordOut] = Field(default_factory=list)


class DeletionResponse(BaseModel):
    request_id: UUID
    status: Literal["pending"] = "pending"
    requested_at: datetime
    scheduled_for: datetime

    @field_serializer("requested_at", "scheduled_for")
    def _serialize_timestamps(self, value: datetime) -> datetime:
        return _as_utc(value)


class ExportResponse(BaseModel):
    schema_version: str = "p0.1"
    exported_at: datetime
    user: MeUser
    profile: Optional[ProfileOut] = None
    equipment: List[str] = Field(default_factory=list)
    injuries: List[InjuryOut] = Field(default_factory=list)
    consents: List[ConsentRecordOut] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)
    account: Dict[str, Any] = Field(default_factory=dict)

    @field_serializer("exported_at")
    def _serialize_exported_at(self, value: datetime) -> datetime:
        return _as_utc(value)
