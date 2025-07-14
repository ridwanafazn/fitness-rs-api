# app/rules/rule_engine.py
from experta import KnowledgeEngine, Fact, Field, Rule
from typing import List, Dict, Tuple


# ────────────────────────────────────────────────────────────────
# 1.  Facts persis notebook
class UserInput(Fact):
    gender = Field(str, default="unknown")
    bmi = Field(float, default=0.0)
    injuries = Field(list, default=[])
    available_days = Field(int, default=1)
    preferred_body_part = Field(list, default=[])


class Recommendation(Fact):
    split_method = Field(str, default="")
    schedule = Field(dict, default={})


# ────────────────────────────────────────────────────────────────
# 2.  Rule Engine
class FitnessRuleEngine(KnowledgeEngine):
    """Port utuh dari notebook decide_recommendation."""

    # ---------- helper internal ----------
    @staticmethod
    def _score_focus(focus: str, user_data: dict) -> int:
        score = 0
        if user_data["preferred_body_part"]:
            if focus in user_data["preferred_body_part"]:
                score += 5
        if user_data["injuries"]:
            if focus in user_data["injuries"]:
                score -= 100
        return score

    @staticmethod
    def _priority_score(focus: str, gender: str) -> int:
        if gender.lower() == "female":
            priority = {"glutes": 0, "quadriceps": 1, "hamstrings": 2, "abs": 3}
        elif gender.lower() == "male":
            priority = {
                "chest": 1,
                "shoulders": 2,
                "biceps": 3,
                "triceps": 4,
                "back": 5,
                "abs": 6,
            }
        else:
            priority = {}
        return priority.get(focus, 100)

    # ---------- main rule ----------
    @Rule(UserInput())
    def decide_recommendation(self):
        d = self.facts[1]          # ← fact UserInput
        days = d["available_days"]
        gender = d["gender"]
        bmi = d["bmi"]

        schedule: Dict[str, str] = {}
        split = "fullbody"

        # 1️⃣  Tentukan split
        if days == 1:
            split = "fullbody"
            schedule["day_1"] = "fullbody"
        elif days == 2:
            split = "upperlower"
            schedule = {"day_1": "upper", "day_2": "lower"}
        elif days == 3:
            split = "ppl"
            schedule = {"day_1": "push", "day_2": "pull", "day_3": "legs"}
        elif days == 4:
            split = "upperlower"
            schedule = {
                "day_1": "upper",
                "day_2": "lower",
                "day_3": "upper",
                "day_4": "lower",
            }
        elif days == 5:
            split = "ppl+focus"
            schedule = {"day_1": "push", "day_2": "pull", "day_3": "legs"}

            focus_options = (
                ["glutes", "quadriceps", "hamstrings", "abs"]
                if gender.lower() == "female"
                else ["chest", "biceps", "triceps", "shoulders", "back", "abs"]
            )

            # if not d["preferred_body_part"]:
            #     sorted_focus = sorted(focus_options, key=lambda x: self._priority_score(x, gender))
            # else:
            scores = {f: self._score_focus(f, d) for f in focus_options}
            sorted_focus = [k for k, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]

            schedule["day_4"] = sorted_focus[0]
            schedule["day_5"] = sorted_focus[1]

        # 2️⃣  Sisipkan cardio bila BMI >= 25
        if bmi >= 25.0:
            cardio_days = 2 if days >= 4 else 1
            inserted = 0
            targets = ["legs", "lower", "fullbody"]

            # ganti prioritas rendah
            for day in range(1, days + 1):
                if inserted >= cardio_days:
                    break
                key = f"day_{day}"
                focus = schedule.get(key)
                if (
                    focus in targets
                    and self._score_focus(focus, d) <= 0
                    and (day == 1 or schedule.get(f"day_{day-1}") != "cardio")
                ):
                    schedule[key] = "cardio"
                    inserted += 1

            # fallback netral
            for day in range(days, 0, -1):
                if inserted >= cardio_days:
                    break
                key = f"day_{day}"
                prev = f"day_{day-1}"
                focus = schedule.get(key)
                if focus != "cardio" and self._score_focus(focus, d) <= 0 and schedule.get(prev) != "cardio":
                    schedule[key] = "cardio"
                    inserted += 1

        # 3️⃣  Simpan fact rekomendasi
        self.declare(Recommendation(split_method=split, schedule=schedule))

    # ---------- public API ----------
    def get_result(self) -> Tuple[str, Dict[str, str]]:
        """Return (split, schedule) setelah engine.run()."""
        for f in self.facts.values():
            if isinstance(f, Recommendation):
                return f["split_method"], f["schedule"]
        return "fullbody", {"day_1": "fullbody"}