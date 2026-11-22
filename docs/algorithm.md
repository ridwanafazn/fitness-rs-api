# Algorithm notes

This document is the implementation-level source of truth for the recommender.
It intentionally records where the code differs from the 2025 thesis.

## 1. Inputs

| Field | Type | Bounds |
|---|---|---|
| `gender` | `male` / `female` | required |
| `height_cm` | float | 50 < x ≤ 300 |
| `weight_kg` | float | 10 < x ≤ 400 |
| `injuries` | list[str] | ≤ 10 items, each ≤ 60 chars |
| `available_days` | int | 1–7 (6–7 capped to 5 for compatibility) |
| `preferred_body_part` | list[enum] | ≤ 5 |
| `preferred_equipment` | list[enum] | ≤ 10 |
| `seed` | int | 0 ≤ x < 2³² |

BMI is computed as `weight_kg / (height_m ** 2)`, rounded to 2 decimals.
BMI ≥ 25 is treated as overweight, matching WHO/Kemenkes.

## 2. Rule table

| Days | BMI < 25 | BMI ≥ 25 |
|---:|---|---|
| 1 | fullbody | cardio |
| 2 | upper, lower | upper, cardio |
| 3 | push, pull, legs | upper, lower, cardio |
| 4 | upper, lower, upper, lower | upper, cardio, lower, cardio |
| 5 | push, pull, legs, focus1, focus2 | upper, cardio, focus1, cardio, lower |

`focus1`/`focus2` are ranked from:

1. the user's valid preferred body parts (+5 each), then
2. gender defaults, then
3. body parts that are not injured.

Injured body parts receive a large negative score and are moved to the end.
If no safe body part exists for a scheduled day, the day is replaced with a
safe alternative and the response includes a warning. For an explicit
`by-focus` request with no safe exercises, the API returns `422` instead of
silently recommending an injured area.

**Documented difference from thesis Table 3.9:** the 3-day BMI ≥ 25 case is
`upperlower` (`upper`, `lower`, `cardio`), not `ppl`; the 5-day BMI ≥ 25 case is
`upperlower+focus`, not `ppl+focus`. This matches the trainer's recommendation
and the actual implementation.

If a scheduled focus does not have enough safe body parts to remain meaningful
(for example, a knee injury removes quadriceps, hamstrings, glutes, and calves
from a lower day), the day is replaced with a specific safe focus or `cardio`.
The response includes a warning explaining the substitution. This avoids
rejecting an otherwise valid upper-body plan merely because one day cannot be
filled safely.

## 3. Focus → body parts

| Focus | Body parts |
|---|---|
| fullbody | all except cardio |
| upper | neck, shoulders, chest, back, abs, biceps, triceps, forearms |
| lower | glutes, quadriceps, hamstrings, calves |
| push | shoulders, chest, triceps |
| pull | back, biceps, forearms, neck |
| legs | glutes, quadriceps, hamstrings, calves |
| cardio | cardio |
| specific | that body part |

## 4. Injury policy

Safety is a **hard constraint**:

1. The API validates injury terms against a supported vocabulary.
2. Terms are mapped to body parts (joints and common regions included).
3. The candidate pool excludes every mapped body part.
4. The GA's gene space is built only from the safe pool.
5. The final output is checked again; an injured body part aborts the response.

Common mappings:

| Input | Avoid |
|---|---|
| `knee`, `acl`, `meniscus`, `patella` | quadriceps, hamstrings, glutes, calves |
| `lower back`, `low back`, `sciatica` | back, glutes, hamstrings |
| `shoulder`, `rotator cuff` | shoulders, chest, triceps (+ back for cuff) |
| `elbow`, `tennis elbow` | biceps, triceps, forearms |
| `wrist` | forearms |
| `ankle` | calves |
| `hip` | glutes, quadriceps, hamstrings |

The mapping is deliberately conservative. It does not yet distinguish
movement patterns (e.g. deep knee flexion vs. hip hinge).

## 5. Exercise filtering

For each day:

1. Drop injured body parts.
2. Keep exercises matching the day focus.
3. Prefer the user's equipment; body-weight is always allowed.
4. If the pool is too small, relax equipment, then focus — **never injuries**.
5. If the safe pool is still smaller than the GA needs, return `422`.

`min_required` equals the number of genes for that focus (3 cardio, 4 specific,
5 composite).

## 6. Genetic algorithm

- One GA run per day.
- Gene = index into that day's safe pool.
- Chromosome = exercise selection for that day.
- `allow_duplicate_genes=False`.
- Exercises already selected on an earlier day are removed from the pool when
  possible; a small cross-day penalty applies only when the pool is too small
  to avoid reuse.
- Defaults: 25 generations, population 20, 8 parents, tournament selection,
  uniform crossover, random mutation 12% of genes, 3 kept parents,
  `saturate_8`.

Fitness (higher is better):

| Term | Weight |
|---|---:|
| Body part matches focus | +2 |
| Body part does not match focus | −3 |
| Body part is preferred | +1 |
| Body part is injured | −1000 (defence in depth) |
| Duplicate body part | −2 each |
| Body-part spread penalty | up to +10 |
| 3/4/5+ unique body parts | −2/−3/−5 |
| Muscle variation | penalties |
| More than one run / indoor cardio | −10 each |

Specific body-part days and cardio days are exempt from the body-part spread
term; otherwise every chest day would be penalised for being a chest day.

The original thesis described a chromosome as one week with genes as days.
The production implementation optimises **one day at a time** because it is
faster, easier to constrain, and matches the notebook's final design.

## 7. Reproducibility

- Every response includes the `seed`.
- The same seed, dataset version, dependency versions, and request produce the
  same output.
- PyGAD's `random_seed` is set per day (`seed + day_index`).
- Pin dependency versions (`requirements.txt`) and record `dataset_version`.

## 8. Evaluation boundary

The system produces an initial exercise schedule. It does not prescribe sets,
reps, load, RPE, tempo, rest, or progression. Those require a different
knowledge base and should not be inferred from this API.
