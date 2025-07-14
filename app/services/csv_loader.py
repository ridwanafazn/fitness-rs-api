# app/services/csv_loader.py
from functools import lru_cache
import pandas as pd
import math


def _split(val):
    if val is None or (isinstance(val, float) and math.isnan(val)) or str(val).strip() == "":
        return []
    return [v.strip() for v in str(val).split("|") if v.strip()]


@lru_cache
def load_exercises() -> pd.DataFrame:
    df = pd.read_csv("data/fitness_dataset.csv")

    # ubah kolom multi‑value menjadi list
    for col in ["equipment", "primary_muscle", "secondary_muscle"]:
        if col in df.columns:
            df[col] = df[col].apply(_split)

    return df