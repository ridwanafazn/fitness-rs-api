import numpy as np
import pandas as pd
from collections import Counter
from experta import KnowledgeEngine, Fact, Field, Rule

# ================= 1. Mapping muscle ke body part =================

muscle_to_body_part = {
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

# ================= 2. Fungsi cek fokus otot sesuai hari =================

def is_exercise_focus(exercise_body_part, day_focus):
    day_focus = day_focus.lower()
    exercise_body_part = exercise_body_part.lower()

    neck_parts = {"neck"}
    shoulders_parts = {"shoulders"}
    chest_parts = {"chest"}
    back_parts = {"back"}
    abs_parts = {"abs"}
    biceps_parts = {"biceps"}
    triceps_parts = {"triceps"}
    forearms_parts = {"forearms"}
    glutes_parts = {"glutes"}
    quadriceps_parts = {"quadriceps"}
    hamstrings_parts = {"hamstrings"}
    calves_parts = {"calves"}
    cardio_parts = {"cardio"}

    upper_parts = chest_parts | biceps_parts | triceps_parts | back_parts | shoulders_parts | forearms_parts | neck_parts | abs_parts
    lower_parts = quadriceps_parts | glutes_parts | calves_parts | hamstrings_parts
    push_parts = chest_parts | triceps_parts | shoulders_parts
    pull_parts = back_parts | biceps_parts | forearms_parts | neck_parts
    legs_parts = quadriceps_parts | glutes_parts | calves_parts | hamstrings_parts

    male_focus_parts = chest_parts | shoulders_parts | biceps_parts | triceps_parts | back_parts | abs_parts
    female_focus_parts = glutes_parts | quadriceps_parts | hamstrings_parts | abs_parts

    if day_focus == "upper":
        return exercise_body_part in upper_parts
    elif day_focus == "lower":
        return exercise_body_part in lower_parts
    elif day_focus == "push":
        return exercise_body_part in push_parts
    elif day_focus == "pull":
        return exercise_body_part in pull_parts
    elif day_focus == "legs":
        return exercise_body_part in legs_parts
    elif day_focus == "fullbody":
        return True
    elif day_focus == "cardio":
        return exercise_body_part == "cardio"
    elif day_focus == "male_focus":
        return exercise_body_part in male_focus_parts
    elif day_focus == "female_focus":
        return exercise_body_part in female_focus_parts
    else:
        return exercise_body_part == day_focus

# ================= 3. Rule-Based System dengan Experta =================

class UserInput(Fact):
    gender = Field(str, default='unknown')
    bmi = Field(float, default=0.0)
    injuries = Field(list, default=[])
    available_days = Field(int, default=1)
    preferred_body_part = Field(list, default=[])

class Recommendation(Fact):
    split_method = Field(str, default='')
    schedule = Field(dict, default={})

class FitnessRuleEngine(KnowledgeEngine):

    def _score_focus(self, focus, user_data):
        score = 0
        if user_data['preferred_body_part']:
            if focus in user_data['preferred_body_part']:
                score += 5
        if user_data['injuries']:
            if focus in user_data['injuries']:
                score -= 100
        return score

    def _priority_score(self, focus, gender):
        if gender.lower() == 'female':
            priority = {
                'glutes': 0,
                'quadriceps': 1,
                'hamstrings': 2,
                'abs': 3,
            }
        elif gender.lower() == 'male':
            priority = {
                'chest': 1,
                'shoulders': 2,
                'biceps': 3,
                'triceps': 4,
                'back': 5,
                'abs': 6,
            }
        else:
            priority = {}
        return priority.get(focus, 100)

    @Rule(UserInput())
    def decide_recommendation(self):
        d = self.facts[1]
        days = d['available_days']
        gender = d['gender']
        bmi = d['bmi']

        schedule = {}
        split = 'fullbody'

        if days == 1:
            split = 'fullbody'
            schedule['day_1'] = 'fullbody'
        elif days == 2:
            split = 'upperlower'
            schedule = {
                'day_1': 'upper',
                'day_2': 'lower',
            }
        elif days == 3:
            split = 'ppl'
            schedule = {
                'day_1': 'push',
                'day_2': 'pull',
                'day_3': 'legs',
            }
        elif days == 4:
            split = 'upperlower'
            schedule = {
                'day_1': 'upper',
                'day_2': 'lower',
                'day_3': 'upper',
                'day_4': 'lower',
            }
        elif days == 5:
            split = 'ppl+focus'
            schedule = {
                'day_1': 'push',
                'day_2': 'pull',
                'day_3': 'legs',
            }

            if gender.lower() == 'female':
                focus_options = ['glutes','quadriceps', 'hamstrings', 'abs']
            else:
                focus_options = ['chest', 'biceps', 'triceps', 'shoulders', 'back', 'abs']

            if not d['preferred_body_part']:
                sorted_focus = sorted(focus_options, key=lambda x: self._priority_score(x, gender))
            else:
                scores = {f: self._score_focus(f, d) for f in focus_options}
                sorted_focus = sorted(scores.items(), key=lambda x: x[1], reverse=True)
                sorted_focus = [x[0] for x in sorted_focus]

            schedule['day_4'] = sorted_focus[0]
            schedule['day_5'] = sorted_focus[1]

        if bmi >= 25.0:
            cardio_days = 2 if days >= 4 else 1
            inserted = 0
            cardio_replacement_targets = ['legs', 'lower', 'fullbody']

            for day in range(1, days + 1):
                if inserted >= cardio_days:
                    break
                day_key = f'day_{day}'
                current_focus = schedule.get(day_key)

                if (
                    current_focus in cardio_replacement_targets and
                    self._score_focus(current_focus, d) <= 0 and
                    (day == 1 or schedule.get(f'day_{day - 1}') != 'cardio')
                ):
                    schedule[day_key] = 'cardio'
                    inserted += 1

            for day in range(days, 0, -1):
                if inserted >= cardio_days:
                    break
                day_key = f'day_{day}'
                prev_day_key = f'day_{day - 1}'
                current_focus = schedule.get(day_key)

                if (
                    current_focus != 'cardio' and
                    self._score_focus(current_focus, d) <= 0 and
                    schedule.get(prev_day_key) != 'cardio'
                ):
                    schedule[day_key] = 'cardio'
                    inserted += 1

        self.declare(Recommendation(split_method=split, schedule=schedule))

# ================= 4. Mapping cedera ke body parts =================

def map_injury_to_body_parts(injuries):
    mapped = set()
    valid_body_parts = set(muscle_to_body_part.values())
    for inj in injuries:
        if inj in valid_body_parts:
            mapped.add(inj)
        elif inj in muscle_to_body_part:
            mapped.add(muscle_to_body_part[inj])
    return mapped

# ================= 5. Filtering latihan per fokus, cedera dan equipment =================

def filter_by_focus(df, focus):
    focus = focus.lower()
    if focus == 'cardio':
        return df[df['body_part'].str.lower() == 'cardio']
    else:
        return df[df['body_part'].str.lower().apply(lambda bp: is_exercise_focus(bp, focus))]

def equipment_filter_fn(eq_list, preferred_equipment):
    return ('body weight' in eq_list) or any(eq in preferred_equipment for eq in eq_list)

def get_daily_exercise(df, focus, injuries, preferred_equipment=None, min_required=5, day_label=""):
    print(f"[Day: {day_label}] Fokus: {focus}")
    preferred_equipment = preferred_equipment or []

    if injuries:
        df_filtered = df[~df['body_part'].isin(injuries)]
        print(f"  • Setelah filter cedera: {len(df_filtered)} latihan (hindari: {list(injuries)})")
    else:
        df_filtered = df

    df_focus = filter_by_focus(df_filtered, focus)
    print(f"  • Setelah filter fokus '{focus}': {len(df_focus)} latihan")

    if preferred_equipment:
        df_focus_eq = df_focus[df_focus['equipment'].apply(lambda eq: equipment_filter_fn(eq, preferred_equipment))]
        print(f"  • Setelah filter preferred equipment: {len(df_focus_eq)} latihan (preferred: {preferred_equipment + ['body weight']})")
    else:
        df_focus_eq = df_focus

    if len(df_focus_eq) >= min_required:
        print(f"    Gunakan hasil final (lengkap): {len(df_focus_eq)} latihan")
        return df_focus_eq.reset_index(drop=True)

    df_bodyweight = df_focus[df_focus['equipment'].apply(lambda eq: 'body weight' in eq)]
    if len(df_bodyweight) >= min_required:
        print(f"  Fallback khusus: hanya body weight: {len(df_bodyweight)} latihan")
        return df_bodyweight.reset_index(drop=True)

    if len(df_focus) >= min_required:
        print(f"  Fallback 1: tanpa filter equipment: {len(df_focus)} latihan")
        return df_focus.reset_index(drop=True)

    if len(df_filtered) >= min_required:
        print(f"  Fallback 2: tanpa filter fokus: {len(df_filtered)} latihan")
        return df_filtered.reset_index(drop=True)

    print(f"  Fallback 3: gunakan semua data awal: {len(df)} latihan")
    return df.reset_index(drop=True)

# ================= 6. Fitness Function & GA Engine =================

BASE_SCORE = 0
MAX_PENALTY = 10

preferred_body_parts_mapped = set()
bmi = 0

cardio_run_exercises = {"run", "run on treadmill"}
cardio_indoor_exercises = {
    "stationary bike run", "elliptical machine walk", "bicycle recline walk",
    "cycle cross trainer", "walking on incline treadmill", "walking on treadmill", "walking"
}
cardio_priority_keywords = {"run", "walk", "jog"}

split_fokus_body_part = {
    "glutes", "quadriceps", "hamstrings", "chest", "back", "biceps", "triceps", "shoulders", "calves", "neck", "abs", "forearms"
}
split_cardio = {"cardio"}
special_focus_body_part = {"male focus", "female focus", "fullbody"}

def penalty_duplicate(dup_count):
    return 2 * dup_count

def check_body_part_variation(seen_parts, day_focus, injured_parts, df_subset):
    unique_parts = set(seen_parts)
    part_counts = Counter(seen_parts)
    most_common_count = part_counts.most_common(1)[0][1] if part_counts else 0

    glossary_expected_parts = {
        "upper": {"neck", "shoulders", "chest", "back", "abs", "biceps", "triceps", "forearms"},
        "lower": {"glutes", "quadriceps", "hamstrings", "calves"},
        "push": {"shoulders", "chest", "triceps"},
        "pull": {"back", "biceps", "forearms"},
        "legs": {"glutes", "quadriceps", "hamstrings", "calves"},
        "fullbody": {"neck", "shoulders", "chest", "back", "abs", "biceps", "triceps", "forearms", "glutes", "quadriceps", "hamstrings", "calves"}
    }

    penalty = 0
    day_focus = day_focus.lower()
    glossary_parts = glossary_expected_parts.get(day_focus, set())
    available_parts = set(df_subset['body_part'].str.lower().unique())
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

def check_muscle_variation(solution_indices, df_subset, day_focus):
    primary_muscles = []
    secondary_muscles = []

    for idx in solution_indices:
        ex = df_subset.iloc[idx]
        primary_raw = ex.get('primary_muscle', [])
        secondary_raw = ex.get('secondary_muscle', [])

        primary_list = primary_raw.split('|') if isinstance(primary_raw, str) else primary_raw
        secondary_list = secondary_raw.split('|') if isinstance(secondary_raw, str) else secondary_raw

        primary_muscles.extend([p.strip().lower() for p in primary_list if p])
        secondary_muscles.extend([s.strip().lower() for s in secondary_list if s])

    unique_primary = set(primary_muscles)
    unique_secondary = set(secondary_muscles)

    penalty = 0
    if len(unique_primary) < 2:
        penalty += 3 * (2 - len(unique_primary))
    if len(unique_secondary) < 2:
        penalty += 2 * (2 - len(unique_secondary))

    return penalty

def is_cardio_exercise(ex_name):
    ex_name = ex_name.lower()
    return any(keyword in ex_name for keyword in cardio_priority_keywords)

def make_fitness_func(day_focus, injured_parts, df_subset):
    day_focus_lower = day_focus.lower()
    is_fokus_split = day_focus_lower in split_fokus_body_part
    is_cardio_split = day_focus_lower in split_cardio
    is_special_focus = day_focus_lower in special_focus_body_part

    def fitness_func(solution, solution_idx):
        score = BASE_SCORE
        penalty = 0

        selected_exercises = df_subset.iloc[solution]
        selected_body_parts = selected_exercises['body_part'].str.lower().tolist()
        selected_names = selected_exercises['exercise_name'].str.lower().tolist()

        # Penalti jika ada cedera muncul
        for part in injured_parts:
            if part in selected_body_parts:
                penalty += 20

        # Penalti duplikasi latihan
        duplicates = len(selected_names) - len(set(selected_names))
        penalty += penalty_duplicate(duplicates)

        # Penalti variasi body part
        penalty += check_body_part_variation(selected_body_parts, day_focus_lower, injured_parts, df_subset)

        # Penalti variasi otot primer dan sekunder
        penalty += check_muscle_variation(solution, df_subset, day_focus_lower)

        # Bonus untuk cardio jika fokus cardio
        if is_cardio_split:
            cardio_count = sum(is_cardio_exercise(name) for name in selected_names)
            score += cardio_count * 2

        # Final score = base - penalty + bonus
        final_score = score - penalty

        return final_score

    return fitness_func

# ================= 7. Genetic Algorithm Engine Modular per Hari =================

import pygad

def run_ga_for_day(day_focus, injured_parts, df_subset, num_generations=50, sol_per_pop=20, num_genes=5):
    fitness_function = make_fitness_func(day_focus, injured_parts, df_subset)

    gene_space = list(range(len(df_subset)))

    def fitness_wrapper(solution, solution_idx):
        return fitness_function(solution, solution_idx)

    ga_instance = pygad.GA(
        num_generations=num_generations,
        num_parents_mating=5,
        fitness_func=fitness_wrapper,
        sol_per_pop=sol_per_pop,
        num_genes=num_genes,
        gene_space=gene_space,
        parent_selection_type="sss",
        crossover_type="single_point",
        mutation_type="random",
        mutation_percent_genes=10,
        suppress_warnings=True,
    )

    ga_instance.run()
    solution, solution_fitness, _ = ga_instance.best_solution()

    selected_exercises = df_subset.iloc[solution]
    return selected_exercises, solution_fitness, ga_instance

# ================= 8. Contoh Penggunaan =================

if __name__ == "__main__":
    # Contoh load dataset
    df = pd.read_csv('dataset_fitness.csv', converters={
        'equipment': lambda x: x.strip("[]").replace("'", "").split(',') if isinstance(x, str) else [],
        'primary_muscle': lambda x: x,
        'secondary_muscle': lambda x: x,
    })

    # Input user
    user_injuries_raw = ['abs']  # contoh cedera
    user_injuries = map_injury_to_body_parts(user_injuries_raw)

    user_days = 3
    user_day_focuses = ['push', 'pull', 'legs']

    # Filter dan GA per hari
    results = {}
    for i, focus in enumerate(user_day_focuses, start=1):
        df_filtered = get_daily_exercise(df, focus, user_injuries, preferred_equipment=['dumbbell', 'barbell'], day_label=f"Day {i}")
        selected_ex, fitness_score, ga = run_ga_for_day(focus, user_injuries, df_filtered)
        results[f'day_{i}'] = {
            'focus': focus,
            'selected_exercises': selected_ex,
            'fitness_score': fitness_score,
        }

    for day, data in results.items():
        print(f"{day} ({data['focus']}): Fitness Score = {data['fitness_score']}")
        print(data['selected_exercises'][['exercise_name', 'body_part', 'equipment']])
        print()