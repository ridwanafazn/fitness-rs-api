from typing import List, Optional, Any
from pydantic import BaseModel, Field, field_validator


class ExerciseOut(BaseModel):
    """
    Representasi satu latihan yang dikirim ke client.
    Field di‑alias agar langsung cocok dengan header CSV.
    """
    exercise_id: str = Field(..., alias="exercise_id")
    exercise_name: str
    body_part: str
    equipment: List[str]
    primary_muscle: List[str]
    secondary_muscle: List[str] = []
    # ↓ ambil dari kolom `exercise_image` di dataset
    image_url: Optional[str] = Field(None, alias="exercise_image")

    # ──────────────────────────────────────────────────────────
    # Normalisasi ID -> string
    @field_validator("exercise_id", mode="before")
    @classmethod
    def _cast_id(cls, v: Any) -> str:
        return str(v)

    # Pastikan kolom list benar‑benar list
    @field_validator("equipment", "primary_muscle", "secondary_muscle", mode="before")
    @classmethod
    def _ensure_list(cls, v: Any) -> List[str]:
        """
        - Jika sudah list ➜ kembalikan apa adanya.
        - Jika string ➜ split by '|' lalu bungkus jadi list.
        - Jika None / NaN ➜ kembalikan list kosong.
        """
        if v is None:
            return []
        if isinstance(v, list):
            return v
        # treat pandas NaN
        try:
            import math
            if isinstance(v, float) and math.isnan(v):
                return []
        except Exception:
            pass
        # string single / pipe‑separated
        return [x.strip() for x in str(v).split("|") if x.strip()]

    model_config = {
        "populate_by_name": True,   # izinkan alias->field
        "from_attributes": True,    # dukung model_validate(dict)
    }