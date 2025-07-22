# app/rules/rule_engine.py

from experta import KnowledgeEngine, Fact, Field, Rule, DefFacts, MATCH, NOT
from typing import List, Dict, Tuple

# ──────────────────────────────────────────────
# Konstanta
PREF_BONUS = 5
INJURY_PENALTY = -100
DEFAULT_PRIORITY_PENALTY = -1

# ──────────────────────────────────────────────
# Facts
class UserInput(Fact):
    """Fakta input pengguna untuk sistem rekomendasi fitness."""
    gender = Field(str, default="unknown")
    bmi = Field(float, default=0.0)
    injuries = Field(list, default=[])
    available_days = Field(int, default=1)
    preferred_body_part = Field(list, default=[])


class Recommendation(Fact):
    """Fakta output rekomendasi jadwal dan metode split."""
    split_method = Field(str, default="")
    schedule = Field(dict, default={})


# ──────────────────────────────────────────────
# Rule Engine
class FitnessRuleEngine(KnowledgeEngine):
    """Engine sistem pakar untuk menentukan rekomendasi program fitness."""

    def _score_focus(self, focus: str, user_data: dict) -> int:
        """
        Hitung skor fokus berdasarkan preferensi dan cedera pengguna.
        """
        score = 0
        if user_data['preferred_body_part'] and focus in user_data['preferred_body_part']:
            score += PREF_BONUS
        if user_data['injuries'] and focus in user_data['injuries']:
            score += INJURY_PENALTY
        return score

    def _priority_score(self, focus: str, gender: str) -> int:
        """
        Memberikan penalti jika pengguna tidak menyebutkan preferensi.
        """
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

    @Rule(UserInput(gender=MATCH.gender,
                    bmi=MATCH.bmi,
                    injuries=MATCH.injuries,
                    available_days=MATCH.days,
                    preferred_body_part=MATCH.pref))
    def decide_recommendation(self, gender, bmi, injuries, days, pref):
        """
        Aturan utama: menentukan metode split dan jadwal berdasarkan input pengguna.
        """
        print(f"Processing recommendation for gender={gender}, BMI={bmi}, days={days}")

        schedule = {}
        split = 'fullbody'

        # Fokus berdasarkan gender
        focus_options = (
            ['glutes', 'quadriceps', 'hamstrings', 'abs']
            if gender.lower() == 'female'
            else ['chest', 'biceps', 'triceps', 'shoulders', 'back', 'abs']
        )

        # Hitung skor fokus
        user_data = {
            'preferred_body_part': pref,
            'injuries': injuries
        }

        scores = {f: self._score_focus(f, user_data) for f in focus_options}

        if not pref:
            for f in focus_options:
                scores[f] += -self._priority_score(f, gender)

        # Urutkan fokus berdasarkan skor
        sorted_focus = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        sorted_focus = [x[0] for x in sorted_focus]
        if len(sorted_focus) < 2:
            sorted_focus += focus_options[:2 - len(sorted_focus)]

        # Tentukan split dan jadwal
        if days == 1:
            split = 'fullbody'
            schedule['day_1'] = 'cardio' if bmi >= 25.0 else 'fullbody'

        elif days == 2:
            split = 'upperlower'
            schedule = {
                'day_1': 'upper',
                'day_2': 'cardio' if bmi >= 25.0 else 'lower'
            }

        elif days == 3:
            if bmi >= 25.0:
                split = 'upperlower'
                schedule = {
                    'day_1': 'upper',
                    'day_2': 'lower',
                    'day_3': 'cardio'
                }
            else:
                split = 'ppl'
                schedule = {
                    'day_1': 'push',
                    'day_2': 'pull',
                    'day_3': 'legs'
                }

        elif days == 4:
            if bmi >= 25.0:
                split = 'upperlower'
                schedule = {
                    'day_1': 'upper',
                    'day_2': 'cardio',
                    'day_3': 'lower',
                    'day_4': 'cardio'
                }
            else:
                split = 'upperlower'
                schedule = {
                    'day_1': 'upper',
                    'day_2': 'lower',
                    'day_3': 'upper',
                    'day_4': 'lower'
                }

        elif days == 5:
            if bmi >= 25.0:
                split = 'upperlower+focus'
                schedule = {
                    'day_1': 'upper',
                    'day_2': 'cardio',
                    'day_3': sorted_focus[0],
                    'day_4': 'cardio',
                    'day_5': 'lower'
                }
            else:
                split = 'ppl+focus'
                schedule = {
                    'day_1': 'push',
                    'day_2': 'pull',
                    'day_3': 'legs',
                    'day_4': sorted_focus[0],
                    'day_5': sorted_focus[1]
                }

        self.declare(Recommendation(split_method=split, schedule=schedule))

    def get_result(self) -> Tuple[str, Dict[str, str]]:
        """
        Mengembalikan split_method dan schedule dari Recommendation yang telah di-declare.
        """
        for f in self.facts.values():
            if isinstance(f, Recommendation):
                return f["split_method"], f["schedule"]
        return "fullbody", {"day_1": "fullbody"}