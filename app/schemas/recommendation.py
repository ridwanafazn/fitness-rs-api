# app/schemas/recommendation.py
from typing import List, Dict, Optional
from pydantic import BaseModel, Field, validator
from app.schemas.exercise import ExerciseOut

VALID_FOCUS = [
    "fullbody", "upper", "lower", "push", "pull", "legs", "cardio",
    "neck", "shoulders", "chest", "back", "abs", "biceps", "triceps",
    "forearms", "glutes", "quadriceps", "hamstrings", "calves"
]

class RecommendationRequest(BaseModel):
    # input body
    gender: str = Field(..., pattern="male|female")
    height_cm: float = Field(..., gt=0)
    weight_kg: float = Field(..., gt=0)
    injuries: List[str] = []
    available_days: int = Field(..., ge=1, le=5)
    preferred_body_part: List[str] = []
    preferred_equipment: List[str] = []

class RecommendationDay(BaseModel):
    day: int
    day_focus: str
    exercises: List[ExerciseOut]

class RecommendationResponse(BaseModel):
    bmi: float
    bmi_category: str
    split_type: str
    schedule: Dict[str, str]
    days: List[RecommendationDay]

class ByFocusRequest(BaseModel):
    day_focus: str
    injuries: List[str] = Field(default_factory=list)
    preferred_equipment: List[str] = Field(default_factory=list)
    preferred_body_part: List[str] = Field(default_factory=list)
    bmi: Optional[float] = None

    @validator("day_focus")
    def validate_day_focus(cls, v):
        if v not in VALID_FOCUS:
            raise ValueError("day_focus tidak valid. Gunakan fokus latihan yang tersedia.")
        return v

class ByFocusResponse(BaseModel):
    day_focus: str
    exercises: List[ExerciseOut]