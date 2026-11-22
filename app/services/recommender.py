"""Recommendation orchestration.

The route layer should not know about rule tables, CSV parsing or PyGAD.  This
service is the single place that composes those pieces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Set, Tuple

from app.core.config import Settings
from app.core.errors import InsufficientPoolError, ServiceUnavailableError
from app.domain.constants import BodyPart, Equipment, Focus
from app.domain.injuries import map_injury_to_body_parts
from app.domain.models import DayPlan, RecommendationPlan, UserProfile
from app.domain.rules import build_rule_result
from app.services.dataset import Dataset
from app.services.exercise_filter import build_daily_pool
from app.services.genetic_optimizer import (
    GAConfig,
    generate_seed,
    run_ga_schedule,
)


@dataclass(frozen=True)
class Recommender:
    dataset: Dataset
    settings: Settings

    def _resolve_seed(self, requested: Optional[int]) -> int:
        if requested is not None:
            return requested
        if self.settings.ga_random_seed is not None:
            return self.settings.ga_random_seed
        return generate_seed()

    def _ga_config(self, seed: int) -> GAConfig:
        return GAConfig(
            num_generations=self.settings.ga_num_generations,
            sol_per_pop=self.settings.ga_sol_per_pop,
            num_parents_mating=self.settings.ga_num_parents_mating,
            mutation_percent_genes=self.settings.ga_mutation_percent_genes,
            keep_parents=self.settings.ga_keep_parents,
            stop_criteria=self.settings.ga_stop_criteria,
            random_seed=seed,
        )

    def _validate_selected(
        self,
        daywise: Dict[str, DayPlan],
        injured_parts: Set[BodyPart],
    ) -> None:
        for day_key, day in daywise.items():
            if not day.exercises:
                raise ServiceUnavailableError(f"Tidak ada latihan yang dihasilkan untuk {day_key}.")
            for exercise in day.exercises:
                if exercise.body_part in injured_parts:
                    # This should be impossible because the pool excludes
                    # injuries; keep the check as a final safety net.
                    raise ServiceUnavailableError(
                        "Sistem menghasilkan latihan pada area cedera; "
                        "output dibatalkan demi keamanan."
                    )

    def recommend(self, profile: UserProfile) -> RecommendationPlan:
        injured_parts = map_injury_to_body_parts(profile.injuries)

        rule_result = build_rule_result(
            gender=profile.gender,
            bmi=profile.bmi,
            available_days=profile.available_days,
            preferred_body_part=profile.preferred_body_part,
            injured_body_parts=injured_parts,
        )

        daily_pool = build_daily_pool(
            schedule=rule_result.schedule,
            dataset=self.dataset,
            injuries=profile.injuries,
            preferred_equipment=profile.preferred_equipment,
        )

        seed = self._resolve_seed(profile.seed)
        daywise = run_ga_schedule(
            rule_result.schedule,
            daily_pool,
            injured_body_parts=injured_parts,
            preferred_body_parts=set(profile.preferred_body_part),
            config=self._ga_config(seed),
        )

        if set(daywise) != set(rule_result.schedule):
            raise ServiceUnavailableError("Jadwal tidak lengkap: beberapa hari gagal dioptimasi.")

        self._validate_selected(daywise, injured_parts)

        days: Tuple[DayPlan, ...] = tuple(daywise[day_key] for day_key in rule_result.schedule)

        return RecommendationPlan(
            bmi=profile.bmi,
            bmi_category=profile.bmi_category,
            split_type=rule_result.split_method,
            schedule=rule_result.schedule,
            days=days,
            seed=seed,
            dataset_version=self.dataset.version,
            algorithm_version=self.settings.app_version,
            warnings=rule_result.warnings,
        )

    def recommend_day(
        self,
        *,
        focus: Focus,
        injuries: Tuple[str, ...] = (),
        preferred_equipment: Tuple[Equipment, ...] = (),
        preferred_body_part: Tuple[BodyPart, ...] = (),
        seed: Optional[int] = None,
    ) -> Tuple[DayPlan, int]:
        injured_parts = map_injury_to_body_parts(injuries)

        daily_pool = build_daily_pool(
            schedule={"day_1": focus},
            dataset=self.dataset,
            injuries=injuries,
            preferred_equipment=preferred_equipment,
        )

        actual_seed = self._resolve_seed(seed)
        daywise = run_ga_schedule(
            {"day_1": focus},
            daily_pool,
            injured_body_parts=injured_parts,
            preferred_body_parts=set(preferred_body_part),
            config=self._ga_config(actual_seed),
        )

        if "day_1" not in daywise:
            raise InsufficientPoolError(
                details={"focus": focus.value, "reason": "no day generated"}
            )

        day = daywise["day_1"]
        self._validate_selected({"day_1": day}, injured_parts)
        return day, actual_seed
