# app/services/genetic_optimizer.py
"""
Pembungkus tahap 9 (Genetic Algorithm) dari notebook.
Parameter GA dan aturan diadopsi dari ipynb versi terbaru.
Output fungsi hanya daywise_schedule (minimalis untuk backend API).

*REFACTORED FOR PRODUCTION: 
Dioptimasi dari sisi efisiensi memori (NumPy/Dict Shift) 
dan Logging standar industri.
"""

from typing import Dict, List, Set
import numpy as np
import pandas as pd
import pygad
import os
import logging
from collections import Counter

# ────────────────────────────────────────────────────────────────
# 1. STANDARISASI LOGGING
# ────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG if os.getenv("DEBUG", "0") == "1" else logging.INFO)
# Tambahkan console handler jika belum ada di main.py
if not logger.handlers:
    ch = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

# ────────────────────────────────────────────────────────────────
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

def penalty_duplicate(dup_count: int) -> int:
    return 2 * dup_count

def check_body_part_variation(seen_parts: List[str], day_focus: str,
                              available_parts: Set[str]) -> int:
    """
    Refactored: Menerima available_parts yang sudah dihitung sekali di awal,
    bukan memproses df_subset berulang kali.
    """
    unique_parts = set(seen_parts)
    part_counts = Counter(seen_parts)
    most_common_count = part_counts.most_common(1)[0][1] if part_counts else 0

    glossary_expected_parts = {
        "upper": {"neck", "shoulders", "chest", "back", "abs", "biceps", "triceps", "forearms"},
        "lower": {"glutes", "quadriceps", "hamstrings", "calves"},
        "push": {"shoulders", "chest", "triceps"},
        "pull": {"back", "biceps", "forearms", "neck"},
        "legs": {"glutes", "quadriceps", "hamstrings", "calves", "abs"},
        "fullbody": {
            "neck", "shoulders", "chest", "back", "abs", "biceps", "triceps",
            "forearms", "glutes", "quadriceps", "hamstrings", "calves",
        },
    }

    penalty = 0
    glossary_parts = glossary_expected_parts.get(day_focus, set())
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

def check_muscle_variation(solution_indices: List[int], records: List[Dict]) -> int:
    """
    Refactored: Membaca dari List of Dictionaries yang sudah di-precompute,
    bukan memanggil pd.DataFrame.iloc[idx] dan melakukan string split berulang kali.
    """
    primary_muscles, secondary_muscles = [], []
    for idx in solution_indices:
        ex = records[int(idx)]
        primary_muscles.extend(ex['precomputed_primary'])
        secondary_muscles.extend(ex['precomputed_secondary'])

    unique_primary = set(primary_muscles)
    unique_secondary = set(secondary_muscles)

    penalty = 0
    if len(unique_primary) < 2:
        penalty += 3 * (2 - len(unique_primary))
    if len(unique_secondary) < 2:
        penalty += 1 * (2 - len(unique_secondary))
    return penalty


def _make_fitness_func(day_focus: str, injured_parts: Set[str],
                       df_subset: pd.DataFrame, preferred_parts: Set[str]):
    focus_lower = day_focus.lower()
    is_fokus_split = focus_lower in split_fokus_body_part
    is_cardio_split = focus_lower in split_cardio
    exercises_per_day = 4 if is_fokus_split else 3 if is_cardio_split else 5

    # ────────────────────────────────────────────────────────────────
    # 2. DATA PRE-COMPUTATION (THE NUMPY/DICT SHIFT)
    # ────────────────────────────────────────────────────────────────
    # Ubah DataFrame menjadi List of Dicts agar akses O(1) dan sangat cepat
    records = df_subset.to_dict('records')
    available_parts_set = set()

    for r in records:
        # Pre-compute string operations
        bp_lower = str(r.get("body_part", "")).lower()
        r['precomputed_body_part'] = bp_lower
        r['precomputed_ex_name'] = str(r.get("exercise_name", "")).lower()
        available_parts_set.add(bp_lower)

        # Pre-compute muscle splits
        p_raw = r.get("primary_muscle", [])
        s_raw = r.get("secondary_muscle", [])
        p_list = p_raw.split("|") if isinstance(p_raw, str) else (p_raw if isinstance(p_raw, list) else [])
        s_list = s_raw.split("|") if isinstance(s_raw, str) else (s_raw if isinstance(s_raw, list) else [])
        
        r['precomputed_primary'] = [p.strip().lower() for p in p_list if p]
        r['precomputed_secondary'] = [s.strip().lower() for s in s_list if s]

    def fitness_func(ga_instance, solution, _solution_idx):
        score = BASE_SCORE
        seen_body_parts, run_cnt, indoor_cnt, cardio_slots = [], 0, 0, 0

        for idx in solution:
            # FAST ACCESS: Menggunakan list index murni (hilangkan bottleneck Pandas)
            ex = records[int(idx)]
            body_part = ex['precomputed_body_part']
            
            # Penalti cedera
            if body_part in injured_parts:
                score -= 5

            # Penalti/favor fokus hari
            if not (body_part == day_focus or body_part in day_focus):
                score -= 3
            else:
                score += 2

            # Preferensi user
            if body_part in preferred_parts:
                score += 1

            seen_body_parts.append(body_part)

        # Penalti variasi body part (lempar set yang sudah dihitung sekali)
        score -= check_body_part_variation(seen_body_parts, focus_lower, available_parts_set)

        # Penalti variasi otot
        score -= check_muscle_variation(solution, records)

        # Penalti duplikat body part
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

        if ga_instance.generations_completed == 0:
            score -= np.random.uniform(2, 5)

        return score

    return fitness_func

def should_add_preference_gene(focus_name: str, preferred_parts: Set[str]) -> bool:
    focus_name = focus_name.lower()

    focus_map = {
        "fullbody": {"neck", "shoulders", "chest", "back", "abs", "biceps", "triceps", "forearms", "glutes", "quadriceps", "hamstrings", "calves"},
        "upper": {"neck", "shoulders", "chest", "back", "abs", "biceps", "triceps", "forearms"},
        "lower": {"glutes", "quadriceps", "hamstrings", "calves"},
        "push": {"shoulders", "chest", "triceps"},
        "pull": {"back", "biceps", "forearms"},
        "legs": {"glutes", "quadriceps", "hamstrings", "calves", "abs"},
        "male focus": {"chest", "shoulders", "biceps", "triceps", "back", "abs"},
        "female focus": {"glutes", "quadriceps", "hamstrings", "abs"},
        "cardio": {"cardio"},
    }

    if focus_name not in focus_map or focus_name in {"male focus", "female focus"}:
        return False

    overlap = preferred_parts & focus_map[focus_name]
    return len(overlap) >= 1

def run_ga_schedule(
    schedule: Dict[str, str],
    daily_exercise_pool: Dict[str, pd.DataFrame],
    injured_body_parts: List[str],
    preferred_body_parts: List[str] = None,
    bmi: float = 0.0,
) -> Dict[str, Dict]:
    injured_parts_set = set(map(str.lower, injured_body_parts or []))
    preferred_parts_set = set(map(str.lower, preferred_body_parts or []))

    daywise_schedule: Dict[str, Dict] = {}

    for day_key, focus in schedule.items():
        df_day = daily_exercise_pool.get(day_key)
        if df_day is None or df_day.empty:
            logger.warning(f"[GA] {day_key} pool kosong — dilewati.")
            continue

        gene_space = list(range(len(df_day)))

        base_genes = 4 if focus.lower() in split_fokus_body_part else 3 if focus.lower() in split_cardio else 5
        bonus_gene = 1 if should_add_preference_gene(focus, preferred_parts_set) else 0
        num_genes = base_genes + bonus_gene

        ga = pygad.GA(
            allow_duplicate_genes=False,
            num_generations=25,
            sol_per_pop=20,      
            num_parents_mating=8,        
            fitness_func=_make_fitness_func(
                focus, injured_parts_set, df_day, preferred_parts_set
            ),
            num_genes=num_genes,
            gene_type=int,
            gene_space=gene_space,
            parent_selection_type="tournament",
            crossover_type="uniform",
            mutation_type="random",
            mutation_percent_genes=12,   
            keep_parents=3,
            stop_criteria=["saturate_8"], 
            save_solutions=False,
            suppress_warnings=True,
            on_generation=None,
        )

        logger.info(f"Running GA for {day_key} ({focus}), pool size: {len(df_day)}")
        ga.run()

        best_genes = ga.best_solution()[0]
        selected = [df_day.iloc[int(idx)].to_dict() for idx in best_genes]

        if focus.lower() == "cardio":
            run_indices = [i for i, ex in enumerate(selected) if ex["exercise_name"].lower() in cardio_run_exercises]
            indoor_indices = [i for i, ex in enumerate(selected) if ex["exercise_name"].lower() in cardio_indoor_exercises]

            if run_indices:
                selected = [selected[run_indices[0]]]
            elif indoor_indices:
                if len(selected) > 2:
                    selected_sorted = [selected[i] for i in indoor_indices] + [
                        selected[i] for i in range(len(selected)) if i not in indoor_indices
                    ]
                    selected = selected_sorted[:2]

        daywise_schedule[day_key] = {
            "focus": focus,
            "exercises": selected,
        }

    return daywise_schedule