"""
Pembungkus tahap 9 (Genetic Algorithm) dari notebook.
Semua *tuning parameter* (generations, population size, dsb.) dibiarkan
PERSIS sama; hanya noise‐logging & visualisasi yang dihilangkan.

Fungsi publik: `run_ga_schedule(schedule, daily_pool, injured_parts)`
mengembalikan `daywise_schedule` siap dikonversi ke schema response.
"""

from typing import Dict, List, Set
import numpy as np
import pandas as pd
import pygad
import os

# ────────────────────────────────────────────────────────────────
# 1.  Utils logging ringan
DEBUG = os.getenv("DEBUG", "0") == "1"
def _log(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


# ────────────────────────────────────────────────────────────────
# 2.  Konstanta & helper persis seperti notebook
BASE_SCORE = 0
MAX_PENALTY = 10

split_fokus_body_part = {
    "glutes", "quadriceps", "hamstrings", "chest", "back", "biceps",
    "triceps", "shoulders", "calves", "neck", "abs", "forearms",
}
split_cardio = {"cardio"}
special_focus_body_part = {"male focus", "female focus", "fullbody"}

cardio_run_exercises = {"run", "run on treadmill"}
cardio_indoor_exercises = {
    "stationary bike run", "elliptical machine walk", "bicycle recline walk",
    "cycle cross trainer", "walking on incline treadmill",
    "walking on treadmill", "walking",
}
cardio_priority_keywords = {"run", "walk", "jog"}


def penalty_duplicate(dup_count: int) -> int:
    return 2 * dup_count


def check_body_part_variation(seen_parts: List[str], day_focus: str,
                              injured_parts: Set[str], df_subset: pd.DataFrame) -> int:
    from collections import Counter

    unique_parts = set(seen_parts)
    part_counts = Counter(seen_parts)
    most_common_count = part_counts.most_common(1)[0][1] if part_counts else 0

    glossary_expected_parts = {
        "upper": {"neck", "shoulders", "chest", "back", "abs", "biceps", "triceps", "forearms"},
        "lower": {"glutes", "quadriceps", "hamstrings", "calves"},
        "push": {"shoulders", "chest", "triceps"},
        "pull": {"back", "biceps", "forearms", "neck"},
        "legs": {"glutes", "quadriceps", "hamstrings", "calves"},
        "fullbody": {
            "neck", "shoulders", "chest", "back", "abs", "biceps", "triceps",
            "forearms", "glutes", "quadriceps", "hamstrings", "calves",
        },
    }

    penalty = 0
    glossary_parts = glossary_expected_parts.get(day_focus, set())
    available_parts = set(df_subset["body_part"].str.lower().unique())
    available_glossary_parts = glossary_parts & available_parts
    n_available = len(available_glossary_parts)

    if n_available >= 3:
        if len(unique_parts) < 3:
            penalty += MAX_PENALTY
        if most_common_count >= 4:
            penalty += MAX_PENALTY
        if len(unique_parts) == 3:
            penalty -= 2
        elif len(unique_parts) == 4:
            penalty -= 3
        elif len(unique_parts) >= 5:
            penalty -= 5
    else:
        if len(unique_parts) < 2:
            penalty += MAX_PENALTY

    return penalty


def check_muscle_variation(solution_indices: List[int], df_subset: pd.DataFrame,
                           day_focus: str) -> int:
    primary_muscles, secondary_muscles = [], []
    for idx in solution_indices:
        ex = df_subset.iloc[idx]
        primary_raw = ex.get("primary_muscle", [])
        secondary_raw = ex.get("secondary_muscle", [])

        primary_list = primary_raw.split("|") if isinstance(primary_raw, str) else primary_raw
        secondary_list = secondary_raw.split("|") if isinstance(secondary_raw, str) else secondary_raw

        primary_muscles.extend([p.strip().lower() for p in primary_list if p])
        secondary_muscles.extend([s.strip().lower() for s in secondary_list if s])

    unique_primary = set(primary_muscles)
    unique_secondary = set(secondary_muscles)

    penalty = 0
    if len(unique_primary) < 2:
        penalty += 3 * (2 - len(unique_primary))
    if len(unique_secondary) < 2:
        penalty += 1 * (2 - len(unique_secondary))
    return penalty


def is_cardio_exercise(ex_name: str) -> bool:
    ex_lower = ex_name.lower()
    return any(k in ex_lower for k in cardio_priority_keywords)


# ────────────────────────────────────────────────────────────────
# 3.  Factory pembuat fitness‑function per hari
def _make_fitness_func(day_focus: str, injured_parts: Set[str],
                       df_subset: pd.DataFrame, preferred_parts: Set[str],
                       bmi: float):
    focus_lower = day_focus.lower()
    is_fokus_split = focus_lower in split_fokus_body_part
    is_cardio_split = focus_lower in split_cardio
    is_special_focus = focus_lower in special_focus_body_part
    exercises_per_day = 4 if is_fokus_split else 3 if is_cardio_split else 5

    def fitness_func(ga_instance, solution, _solution_idx):
        score = BASE_SCORE
        seen_body_parts, run_cnt, indoor_cnt, cardio_slots = [], 0, 0, 0

        for idx in solution:
            ex = df_subset.iloc[idx]
            body_part = ex["body_part"].lower()
            ex_name = ex["exercise_name"].lower()

            # Hindari cedera
            if body_part in injured_parts:
                score -= 5

            # Fokus hari
            if body_part == day_focus or body_part in day_focus:
                score += 2
            else:
                score -= 3

            # Preferensi user
            if body_part in preferred_parts:
                score += 1

            seen_body_parts.append(body_part)

            # Skor cardio utk BMI < 30
            if body_part == "cardio" and bmi < 30.0 and is_cardio_exercise(ex_name):
                score += 2

            # Hitung slot cardio
            if body_part == "cardio":
                if any(r in ex_name for r in cardio_run_exercises):
                    run_cnt += 1
                    cardio_slots += 4
                elif any(i in ex_name for i in cardio_indoor_exercises):
                    indoor_cnt += 1
                    cardio_slots += 3
                else:
                    cardio_slots += 1
            else:
                cardio_slots += 1

        # Penalti variasi
        score -= check_body_part_variation(seen_body_parts, focus_lower, injured_parts, df_subset)
        if is_cardio_split or is_special_focus:
            score -= check_muscle_variation(solution, df_subset, focus_lower)

        # Penalti duplikat
        dup = len(seen_body_parts) - len(set(seen_body_parts))
        if dup:
            score -= penalty_duplicate(dup)

        # Penalti run/indoor berlebih
        if run_cnt > 1 or (run_cnt == 1 and len(solution) > 1):
            score -= MAX_PENALTY
        if indoor_cnt > 1 or (indoor_cnt == 1 and len(solution) > 2):
            score -= MAX_PENALTY

        # Penalti slot cardio melebihi ekspektasi
        if cardio_slots > exercises_per_day:
            score -= (cardio_slots - exercises_per_day) * 2

        # Noise negatif ringan hanya di generasi pertama
        if ga_instance.generations_completed == 0:
            score -= np.random.uniform(2, 5)

        return score

    return fitness_func


# ────────────────────────────────────────────────────────────────
# 4.  Fungsi publik: menjalankan GA utk seluruh minggu
def run_ga_schedule(
    schedule: Dict[str, str],
    daily_exercise_pool: Dict[str, pd.DataFrame],
    injured_body_parts: List[str],
    preferred_body_parts: List[str] = None,
    bmi: float = 0.0,
) -> Dict[str, Dict]:
    """
    Parameters
    ----------
    schedule:       mapping keluaran Rule Engine, e.g. {'day_1':'upper', ...}
    daily_exercise_pool: dict day_key → DataFrame latihan yg sudah difilter
    injured_body_parts:  list cedera (lowercase)
    preferred_body_parts: list preferensi user
    bmi:  nilai BMI user (digunakan di fitness score cardio)

    Returns
    -------
    daywise_schedule dict:
        { 'day_1': {'focus':'upper', 'exercises':[exercise_dict, ...]}, ... }
    """
    injured_parts_set = set(map(str.lower, injured_body_parts or []))
    preferred_parts_set = set(map(str.lower, preferred_body_parts or []))

    daywise_schedule: Dict[str, Dict] = {}

    for day_key, focus in schedule.items():
        df_day = daily_exercise_pool.get(day_key)
        if df_day is None or df_day.empty:
            _log(f"[GA]   {day_key} pool kosong — dilewati.")
            continue

        gene_space = list(range(len(df_day)))
        num_genes = (
            4 if focus.lower() in split_fokus_body_part
            else 3 if focus.lower() in split_cardio
            else 5
        )

        # Siapkan GA
        ga = pygad.GA(
            allow_duplicate_genes=False,
            num_generations=100,           # ← parameter tuning TIDAK diubah
            num_parents_mating=6,
            fitness_func=_make_fitness_func(
                focus,
                injured_parts_set,
                df_day,
                preferred_parts_set,
                bmi,
            ),
            sol_per_pop=15,
            num_genes=num_genes,
            gene_type=int,
            gene_space=gene_space,
            parent_selection_type="sss",
            crossover_type="uniform",
            mutation_type="random",
            mutation_percent_genes=40,
            stop_criteria=["saturate_20"],
            save_solutions=False,
            suppress_warnings=True,
        )

        _log(f"[GA]   Running for {day_key} ({focus}) pool={len(df_day)}")
        ga.run()

        best_genes = ga.best_solution()[0]
        selected = [df_day.iloc[idx].to_dict() for idx in best_genes]

        daywise_schedule[day_key] = {
            "focus": focus,
            "exercises": selected,
        }

    return daywise_schedule