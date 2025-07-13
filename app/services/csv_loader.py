import pandas as pd
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).parent.parent / "data" / "fitness_dataset.csv"

@lru_cache()
def load_fitness_dataset() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH)
    # Parsing kolom list yang berbentuk string dengan delimiter '|'
    for col in ['equipment', 'primary_muscle', 'secondary_muscle']:
        if col in df.columns:
            df[col] = df[col].fillna("").apply(lambda x: [i.strip() for i in x.split('|')] if x else [])
    return df