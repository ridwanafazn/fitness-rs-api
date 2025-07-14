"""
Membungkus seluruh logika filtering & fallback (tahap 8 di notebook)
tanpa mengubah perhitungan apa pun. Semua print diganti _log() agar
bisa dimatikan di production.
"""

from typing import Dict, List, Set
import pandas as pd
import os

# Toggle debug log via env var DEBUG=1
DEBUG = os.getenv("DEBUG", "0") == "1"
def _log(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


# ================= Glossary muscle → body part =================
muscle_to_body_part: Dict[str, str] = {
    "sternocleidomastoid": "neck",
    "splenius capitis": "neck",
    "splenius cervicis": "neck",
    "front deltoids": "shoulders",
    "side deltoids": "shoulders",
    "rear deltoids": "shoulders",
    "upper chest": "chest",
    "middle chest": "chest",
    "lower chest": "chest",
    "upper traps": "back",
    "lower traps": "back",
    "rotator cuff": "back",
    "teres major": "back",
    "lats": "back",
    "erector spinae": "back",
    "rectus abdominis": "abs",
    "obliques": "abs",
    "serratus": "abs",
    "biceps brachii": "biceps",
    "brachialis": "biceps",
    "long head": "triceps",
    "lateral head": "triceps",
    "medial head": "triceps",
    "brachioradialis": "forearms",
    "flexors": "forearms",
    "extensors": "forearms",
    "gluteus maximus": "glutes",
    "gluteus medius": "glutes",
    "gluteus minimus": "glutes",
    "rectus femoris": "quadriceps",
    "vastus lateralis": "quadriceps",
    "vastus medialis": "quadriceps",
    "vastus intermedius": "quadriceps",
    "biceps femoris": "hamstrings",
    "semitendinosus": "hamstrings",
    "semimembranosus": "hamstrings",
    "gastrocnemius": "calves",
    "soleus": "calves",
    "cardio": "cardio",
}

# =============== Helper: cek body_part cocok fokus hari ===============
def is_exercise_focus(exercise_body_part: str, day_focus: str) -> bool:
    bp = exercise_body_part.lower()
    focus = day_focus.lower()

    neck = {"neck"}
    shoulders = {"shoulders"}
    chest = {"chest"}
    back = {"back"}
    abs_ = {"abs"}
    biceps = {"biceps"}
    triceps = {"triceps"}
    forearms = {"forearms"}
    glutes = {"glutes"}
    quads = {"quadriceps"}
    hams = {"hamstrings"}
    calves = {"calves"}
    cardio = {"cardio"}

    upper = chest | biceps | triceps | back | shoulders | forearms | neck | abs_
    lower = quads | glutes | calves | hams
    push = chest | triceps | shoulders
    pull = back | biceps | forearms | neck
    legs = quads | glutes | calves | hams

    male_focus = chest | shoulders | biceps | triceps | back | abs_
    female_focus = glutes | quads | hams | abs_

    if focus == "upper":
        return bp in upper
    if focus == "lower":
        return bp in lower
    if focus == "push":
        return bp in push
    if focus == "pull":
        return bp in pull
    if focus == "legs":
        return bp in legs
    if focus == "fullbody":
        return True
    if focus == "cardio":
        return bp == "cardio"
    if focus == "male_focus":
        return bp in male_focus
    if focus == "female_focus":
        return bp in female_focus
    # fallback: fokus spesifik body part
    return bp == focus


# =============== Cedera → body_part ===============
def _map_injury_to_body_parts(injuries: List[str]) -> Set[str]:
    mapped = set()
    valid_parts = set(muscle_to_body_part.values())

    for inj in injuries:
        inj_lower = inj.lower()
        if inj_lower in valid_parts:
            mapped.add(inj_lower)
        elif inj_lower in muscle_to_body_part:
            mapped.add(muscle_to_body_part[inj_lower])
    return mapped


# =============== Filter util ===============
def _equipment_filter(eq_list: List[str], preferred: List[str]) -> bool:
    # Selalu izinkan body weight
    return ("body weight" in eq_list) or any(eq in preferred for eq in eq_list)


def _filter_by_focus(df: pd.DataFrame, focus: str) -> pd.DataFrame:
    if focus.lower() == "cardio":
        return df[df["body_part"].str.lower() == "cardio"]
    return df[df["body_part"].str.lower().apply(lambda bp: is_exercise_focus(bp, focus))]


# =============== Core: get_daily_exercise =================
def _get_daily_exercise(
    df: pd.DataFrame,
    focus: str,
    injuries: Set[str],
    preferred_equipment: List[str],
    min_required: int,
) -> pd.DataFrame:
    preferred_equipment = preferred_equipment or []

    # 1. Hindari cedera
    if injuries:
        df_filtered = df[~df["body_part"].str.lower().isin(injuries)]
    else:
        df_filtered = df

    # 2. Fokus hari
    df_focus = _filter_by_focus(df_filtered, focus)

    # 3. Filter alat kecuali body weight
    if preferred_equipment:
        df_focus_eq = df_focus[
            df_focus["equipment"].apply(lambda eq: _equipment_filter(eq, preferred_equipment))
        ]
    else:
        df_focus_eq = df_focus

    # 4. Fallback bertingkat
    if len(df_focus_eq) >= min_required:
        return df_focus_eq.reset_index(drop=True)

    df_bodyweight = df_focus[df_focus["equipment"].apply(lambda eq: "body weight" in eq)]
    if len(df_bodyweight) >= min_required:
        return df_bodyweight.reset_index(drop=True)

    if len(df_focus) >= min_required:
        return df_focus.reset_index(drop=True)

    if len(df_filtered) >= min_required:
        return df_filtered.reset_index(drop=True)

    return df.reset_index(drop=True)


# =============== Public API: build_daily_pool =================
def build_daily_pool(
    schedule: dict,
    df_all: pd.DataFrame,
    injuries: List[str],
    preferred_equipment: List[str],
    min_required: int = 5,
) -> Dict[str, pd.DataFrame]:
    """
    Menghasilkan dict {day_key: DataFrame-pool} untuk setiap hari
    sesuai hasil Rule‑Based Engine.
    """
    injured_parts = _map_injury_to_body_parts(injuries)
    daily_pool: Dict[str, pd.DataFrame] = {}

    for day_key, focus in schedule.items():
        _log(f"[FILTER] {day_key=}, {focus=}")
        daily_pool[day_key] = _get_daily_exercise(
            df=df_all,
            focus=focus,
            injuries=injured_parts,
            preferred_equipment=preferred_equipment,
            min_required=min_required,
        )

    return daily_pool