# app/api/recommendation.py  (hanya fungsi create_recommendation di‑update)
from typing import List, Dict
from fastapi import APIRouter, HTTPException, status
from math import pow

from app.schemas.recommendation import RecommendationRequest, RecommendationResponse, RecommendationDay
from app.schemas.exercise import ExerciseOut
from app.services.csv_loader import load_exercises
from app.services.exercise_filter import build_daily_pool
from app.services.genetic_optimizer import run_ga_schedule
from app.rules.rule_engine import FitnessRuleEngine, UserInput   # ← UserInput = Fact

router = APIRouter()

def _bmi_category(b: float) -> str:
    return ("Underweight" if b < 18.5 else
            "Normal"      if b < 25   else
            "Overweight"  if b < 30   else
            "Obese I"     if b < 35   else
            "Obese II"    if b < 40   else
            "Obese III")

@router.post("/", response_model=RecommendationResponse, status_code=status.HTTP_201_CREATED)
def create_recommendation(req: RecommendationRequest):
    # 1️⃣  Hitung BMI
    bmi = round(req.weight_kg / pow(req.height_cm / 100, 2), 2)
    bmi_cat = _bmi_category(bmi)

    # 2️⃣  Jalankan Rule‑Based Engine (versi notebook)
    engine = FitnessRuleEngine()
    engine.reset()
    engine.declare(UserInput(
        gender=req.gender,
        bmi=bmi,
        injuries=req.injuries,
        available_days=req.available_days,
        preferred_body_part=req.preferred_body_part,
    ))
    engine.run()
    split_type, schedule = engine.get_result()   # schedule dict {day_1: 'upper', ...}

    # 3️⃣  Build exercise pool & GA
    df = load_exercises()
    daily_pool = build_daily_pool(
        schedule=schedule,
        df_all=df,
        injuries=req.injuries,
        preferred_equipment=req.preferred_equipment,
    )
    daywise = run_ga_schedule(
        schedule,
        daily_pool,
        injured_body_parts=req.injuries,
        preferred_body_parts=req.preferred_body_part,
        bmi=bmi,
    )
    if not daywise:
        raise HTTPException(404, "Unable to build workout plan")

    # 4️⃣  Format response
    days_out: List[RecommendationDay] = []
    for i, (dk, info) in enumerate(daywise.items(), 1):
        ex_out = [ExerciseOut.model_validate(e) for e in info["exercises"]]
        days_out.append(RecommendationDay(day=i, day_focus=info["focus"], exercises=ex_out))

    return RecommendationResponse(
        bmi=bmi,
        bmi_category=bmi_cat,
        split_type=split_type,
        schedule=schedule,
        days=days_out,
    )