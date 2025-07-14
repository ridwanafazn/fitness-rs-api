# app/schemas/recommendation.py
from typing import List, Dict
from pydantic import BaseModel, Field
from app.schemas.exercise import ExerciseOut

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
    # meta
    bmi: float
    bmi_category: str
    split_type: str
    schedule: Dict[str, str]          # {"day_1":"upper", ...}
    # detail
    days: List[RecommendationDay]