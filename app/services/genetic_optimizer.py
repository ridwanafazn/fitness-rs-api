"""Genetic algorithm orchestration.

One GA run is performed per training day.  A gene is an index into that day's
safe exercise pool; a chromosome is the set of exercises selected for the day.
Injured body parts are removed from the pool before the GA starts, so safety
does not depend on a penalty weight.

The implementation is deterministic when ``GAConfig.random_seed`` is set and
returns the seed used, which makes research runs reproducible.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Set

import pygad

from app.core.errors import InsufficientPoolError
from app.domain.constants import (
    CARDIO_INDOOR_EXERCISES,
    CARDIO_RUN_EXERCISES,
    BodyPart,
    Focus,
)
from app.domain.fitness import score_solution
from app.domain.focus import num_exercises_for_focus
from app.domain.models import DayPlan, Exercise

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GAConfig:
    num_generations: int = 25
    sol_per_pop: int = 20
    num_parents_mating: int = 8
    mutation_percent_genes: int = 12
    keep_parents: int = 3
    stop_criteria: str = "saturate_8"
    random_seed: Optional[int] = None


def _seed_for_day(base_seed: int, day_index: int) -> int:
    return (base_seed + day_index) % (2**32)


def _post_process_cardio(
    selected: Sequence[Exercise], focus: Focus
) -> List[Exercise]:
    """Keep at most one run or two indoor-cardio exercises on a cardio day."""

    if focus is not Focus.CARDIO:
        return list(selected)

    run_indices = [
        index
        for index, exercise in enumerate(selected)
        if exercise.name_lower in CARDIO_RUN_EXERCISES
    ]
    indoor_indices = [
        index
        for index, exercise in enumerate(selected)
        if exercise.name_lower in CARDIO_INDOOR_EXERCISES
    ]

    if run_indices:
        return [selected[run_indices[0]]]
    if indoor_indices and len(selected) > 2:
        ordered = [selected[index] for index in indoor_indices]
        ordered.extend(
            exercise
            for index, exercise in enumerate(selected)
            if index not in indoor_indices
        )
        return ordered[:2]
    return list(selected)


def _make_fitness_func(
    pool: Sequence[Exercise],
    focus: Focus,
    injured_body_parts: Set[BodyPart],
    preferred_body_parts: Set[BodyPart],
    available_parts: Set[BodyPart],
):
    """Bind the day's context once, avoiding late-binding loop bugs."""

    def fitness_func(ga_instance, solution, _solution_idx):
        selected = [pool[int(index)] for index in solution]
        return score_solution(
            selected,
            focus=focus,
            injured_parts=injured_body_parts,
            preferred_parts=preferred_body_parts,
            available_parts=available_parts,
        )

    return fitness_func


def run_ga_schedule(
    schedule: Mapping[str, Focus],
    daily_exercise_pool: Mapping[str, Sequence[Exercise]],
    *,
    injured_body_parts: Set[BodyPart],
    preferred_body_parts: Set[BodyPart],
    config: Optional[GAConfig] = None,
) -> Dict[str, DayPlan]:
    """Optimise one day at a time and return ``day_key -> DayPlan``.

    Raises:
        InsufficientPoolError: if a day's safe pool is smaller than the number
            of genes required for that focus.
    """

    cfg = config or GAConfig()
    base_seed = (
        cfg.random_seed
        if cfg.random_seed is not None
        else secrets.randbelow(2**32)
    )

    daywise: Dict[str, DayPlan] = {}

    for day_index, (day_key, focus) in enumerate(schedule.items()):
        pool = list(daily_exercise_pool.get(day_key, ()))
        num_genes = num_exercises_for_focus(focus)

        if len(pool) < num_genes:
            raise InsufficientPoolError(
                details={
                    "day": day_key,
                    "focus": focus.value,
                    "required": num_genes,
                    "available": len(pool),
                }
            )

        available_parts = {exercise.body_part for exercise in pool}
        day_seed = _seed_for_day(base_seed, day_index)

        ga = pygad.GA(
            num_generations=cfg.num_generations,
            sol_per_pop=cfg.sol_per_pop,
            num_parents_mating=cfg.num_parents_mating,
            fitness_func=_make_fitness_func(
                pool,
                focus,
                injured_body_parts,
                preferred_body_parts,
                available_parts,
            ),
            num_genes=num_genes,
            gene_type=int,
            gene_space=list(range(len(pool))),
            allow_duplicate_genes=False,
            parent_selection_type="tournament",
            crossover_type="uniform",
            mutation_type="random",
            mutation_percent_genes=cfg.mutation_percent_genes,
            keep_parents=cfg.keep_parents,
            stop_criteria=[cfg.stop_criteria],
            save_solutions=False,
            suppress_warnings=True,
            random_seed=day_seed,
        )

        logger.info(
            "ga_start",
            extra={
                "day": day_key,
                "focus": focus.value,
                "pool_size": len(pool),
                "num_genes": num_genes,
                "seed": day_seed,
            },
        )
        ga.run()

        best_solution, best_fitness, _ = ga.best_solution()
        selected = [pool[int(index)] for index in best_solution]
        selected = _post_process_cardio(selected, focus)

        logger.info(
            "ga_finished",
            extra={
                "day": day_key,
                "focus": focus.value,
                "fitness": float(best_fitness),
                "selected": len(selected),
                "seed": day_seed,
            },
        )

        daywise[day_key] = DayPlan(
            day=day_index + 1,
            focus=focus,
            exercises=tuple(selected),
        )

    return daywise


def generate_seed() -> int:
    """Public helper used by the orchestration layer."""

    return secrets.randbelow(2**32)
