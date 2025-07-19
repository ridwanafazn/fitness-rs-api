# app/rules/rule_engine.py
from experta import KnowledgeEngine, Fact, Field, Rule
from typing import List, Dict, Tuple


# ──────────────────────────────────────────────
# Facts
class UserInput(Fact):
    gender = Field(str, default="unknown")
    bmi = Field(float, default=0.0)
    injuries = Field(list, default=[])
    available_days = Field(int, default=1)
    preferred_body_part = Field(list, default=[])


class Recommendation(Fact):
    split_method = Field(str, default="")
    schedule = Field(dict, default={})


# ──────────────────────────────────────────────
# Rule Engine
class FitnessRuleEngine(KnowledgeEngine):
    def _score_focus(self, focus: str, user_data: dict) -> int:
        score = 0
        if user_data['preferred_body_part'] and focus in user_data['preferred_body_part']:
            score += 5
        if user_data['injuries'] and focus in user_data['injuries']:
            score -= 100
        return score

    def _priority_score(self, focus: str, gender: str) -> int:
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

        # Tentukan focus_options
        if gender.lower() == 'female':
            focus_options = ['glutes', 'quadriceps', 'hamstrings', 'abs']
        else:
            focus_options = ['chest', 'biceps', 'triceps', 'shoulders', 'back', 'abs']

        # Hitung skor
        scores = {}
        for f in focus_options:
            pref_bonus = 5 if (d['preferred_body_part'] and f in d['preferred_body_part']) else 0
            injury_penalty = -100 if d['injuries'] and f in d['injuries'] else 0
            scores[f] = pref_bonus + injury_penalty

        # Tambah penalti jika preferred kosong
        if not d['preferred_body_part']:
            for f in focus_options:
                scores[f] += -self._priority_score(f, gender)

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
        for f in self.facts.values():
            if isinstance(f, Recommendation):
                return f["split_method"], f["schedule"]
        return "fullbody", {"day_1": "fullbody"}
