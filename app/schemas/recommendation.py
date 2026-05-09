# app/schemas/recommendation.py
"""
Refactored for Production:
Meningkatkan kedalaman validasi menggunakan Pydantic v2,
menambahkan contoh data (examples) untuk Swagger UI,
dan memperketat batasan keamanan input (constraints).
"""

from typing import List, Dict, Optional
from pydantic import BaseModel, Field, field_validator, ValidationInfo
from app.schemas.exercise import ExerciseOut

VALID_FOCUS = [
    "fullbody", "upper", "lower", "push", "pull", "legs", "cardio",
    "neck", "shoulders", "chest", "back", "abs", "biceps", "triceps",
    "forearms", "glutes", "quadriceps", "hamstrings", "calves"
]

class RecommendationRequest(BaseModel):
    """
    Schema untuk input pembuatan program fitness.
    Sudah dilengkapi dengan batasan realistis (misal: berat badan tidak mungkin 1000kg).
    """
    gender: str = Field(
        ..., 
        pattern="^(male|female)$",
        description="Jenis kelamin biologis (male/female) untuk prioritas otot."
    )
    height_cm: float = Field(
        ..., 
        gt=50, 
        le=300,
        description="Tinggi badan dalam sentimeter (cm)."
    )
    weight_kg: float = Field(
        ..., 
        gt=10, 
        le=400,
        description="Berat badan dalam kilogram (kg)."
    )
    injuries: List[str] = Field(
        default_factory=list,
        max_length=5,
        description="Daftar area otot yang mengalami cedera. Maksimal 5."
    )
    available_days: int = Field(
        ..., 
        ge=1, 
        le=7, # REFACTORED: Diubah dari le=5 menjadi le=7 (seminggu) agar lebih fleksibel
        description="Jumlah hari yang tersedia dalam seminggu."
    )
    preferred_body_part: List[str] = Field(
        default_factory=list,
        max_length=5,
        description="Daftar area otot yang ingin difokuskan."
    )
    preferred_equipment: List[str] = Field(
        default_factory=list,
        description="Daftar alat yang tersedia (opsional)."
    )

    # Menambahkan konfigurasi untuk dokumentasi Swagger
    model_config = {
        "json_schema_extra": {
            "example": {
                "gender": "male",
                "height_cm": 175.5,
                "weight_kg": 72.0,
                "injuries": ["knee", "lower back"],
                "available_days": 4,
                "preferred_body_part": ["chest", "biceps"],
                "preferred_equipment": ["dumbbell", "barbell"]
            }
        }
    }


class RecommendationDay(BaseModel):
    day: int
    day_focus: str
    exercises: List[ExerciseOut]

class RecommendationResponse(BaseModel):
    bmi: float = Field(..., description="Hasil perhitungan Body Mass Index.")
    bmi_category: str = Field(..., description="Kategori BMI (Normal, Overweight, dll).")
    split_type: str = Field(..., description="Metode split yang direkomendasikan.")
    schedule: Dict[str, str] = Field(..., description="Jadwal harian (misal: day_1: upper).")
    days: List[RecommendationDay]

class ByFocusRequest(BaseModel):
    day_focus: str = Field(..., description="Fokus latihan spesifik.")
    injuries: List[str] = Field(default_factory=list, max_length=5)
    preferred_equipment: List[str] = Field(default_factory=list)
    preferred_body_part: List[str] = Field(default_factory=list, max_length=5)
    bmi: Optional[float] = Field(default=None, gt=0, le=100)

    @field_validator("day_focus")
    @classmethod
    def validate_day_focus(cls, v: str, info: ValidationInfo) -> str:
        """
        REFACTORED: Menggunakan Pydantic v2 @field_validator.
        Mengecek apakah fokus hari valid.
        """
        v_lower = v.lower()
        if v_lower not in VALID_FOCUS:
            raise ValueError(f"Fokus '{v}' tidak valid. Fokus yang tersedia: {', '.join(VALID_FOCUS[:5])}...")
        return v_lower
        
    model_config = {
        "json_schema_extra": {
            "example": {
                "day_focus": "chest",
                "injuries": ["shoulder"],
                "bmi": 24.5
            }
        }
    }

class ByFocusResponse(BaseModel):
    day_focus: str
    exercises: List[ExerciseOut]