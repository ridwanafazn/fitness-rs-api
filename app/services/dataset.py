"""Dataset loading and validation.

The runtime uses the Python standard library instead of pandas.  The dataset is
small (222 rows) and CSV parsing is cheap; dropping pandas removes a heavy
dependency and makes the container much smaller.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Set

from app.core.config import DEFAULT_DATASET_PATH
from app.core.errors import DatasetError
from app.domain.constants import Equipment, coerce_body_part, coerce_equipment
from app.domain.models import Exercise

REQUIRED_COLUMNS = (
    "exercise_id",
    "exercise_name",
    "body_part",
    "equipment",
    "primary_muscle",
    "secondary_muscle",
    "exercise_type",
    "movement_type",
    "exercise_image",
)


def _split_multi(value: Optional[str]) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip().lower() for item in value.split("|") if item.strip())


@dataclass(frozen=True)
class Dataset:
    exercises: tuple[Exercise, ...]
    version: str
    path: Path


def _parse_row(row: Dict[str, str], line_number: int) -> Exercise:
    exercise_id = (row.get("exercise_id") or "").strip()
    exercise_name = (row.get("exercise_name") or "").strip()
    body_part_raw = (row.get("body_part") or "").strip()
    equipment_raw = (row.get("equipment") or "").strip()
    primary_raw = (row.get("primary_muscle") or "").strip()
    exercise_type = (row.get("exercise_type") or "").strip()
    movement_type = (row.get("movement_type") or "").strip()

    if not exercise_id:
        raise DatasetError(f"Baris {line_number}: exercise_id kosong.")
    if not exercise_name:
        raise DatasetError(f"Baris {line_number}: exercise_name kosong.")
    if not body_part_raw:
        raise DatasetError(f"Baris {line_number}: body_part kosong.")
    if not equipment_raw:
        raise DatasetError(f"Baris {line_number}: equipment kosong.")
    if not primary_raw:
        raise DatasetError(f"Baris {line_number}: primary_muscle kosong.")
    if not exercise_type:
        raise DatasetError(f"Baris {line_number}: exercise_type kosong.")
    if not movement_type:
        raise DatasetError(f"Baris {line_number}: movement_type kosong.")

    try:
        body_part = coerce_body_part(body_part_raw)
    except ValueError as exc:
        raise DatasetError(
            f"Baris {line_number}: body_part '{body_part_raw}' tidak dikenal."
        ) from exc

    equipment: List[Equipment] = []
    for item in _split_multi(equipment_raw):
        try:
            equipment.append(coerce_equipment(item))
        except ValueError as exc:
            raise DatasetError(
                f"Baris {line_number}: equipment '{item}' tidak dikenal."
            ) from exc
    if not equipment:
        raise DatasetError(f"Baris {line_number}: equipment kosong.")

    primary = _split_multi(primary_raw)
    if not primary:
        raise DatasetError(f"Baris {line_number}: primary_muscle kosong.")

    return Exercise(
        exercise_id=exercise_id,
        exercise_name=exercise_name,
        body_part=body_part,
        equipment=tuple(equipment),
        primary_muscle=primary,
        secondary_muscle=_split_multi(row.get("secondary_muscle")),
        exercise_type=exercise_type,
        movement_type=movement_type,
        image_url=(row.get("exercise_image") or "").strip() or None,
    )


def load_dataset(path: Optional[Path] = None) -> Dataset:
    """Load and validate the exercise CSV.

    Raises:
        DatasetError: if the file is missing, malformed, or contains unknown
            vocabulary values.
    """

    dataset_path = Path(path) if path is not None else DEFAULT_DATASET_PATH
    if not dataset_path.exists():
        raise DatasetError(f"Dataset tidak ditemukan: {dataset_path}")

    raw = dataset_path.read_bytes()
    version = hashlib.sha256(raw).hexdigest()[:16]

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DatasetError("Dataset harus berupa UTF-8.") from exc

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = tuple(reader.fieldnames or ())
    missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing:
        raise DatasetError(
            f"Kolom dataset tidak lengkap: {', '.join(missing)}"
        )

    exercises: List[Exercise] = []
    seen_ids: Set[str] = set()
    seen_names: Set[str] = set()

    for line_number, row in enumerate(reader, start=2):
        exercise = _parse_row(row, line_number)
        if exercise.exercise_id in seen_ids:
            raise DatasetError(
                f"exercise_id duplikat: {exercise.exercise_id} (baris {line_number})"
            )
        name_key = exercise.exercise_name.strip().lower()
        if name_key in seen_names:
            raise DatasetError(
                f"exercise_name duplikat: {exercise.exercise_name} (baris {line_number})"
            )
        seen_ids.add(exercise.exercise_id)
        seen_names.add(name_key)
        exercises.append(exercise)

    if not exercises:
        raise DatasetError("Dataset tidak berisi latihan.")

    return Dataset(exercises=tuple(exercises), version=version, path=dataset_path)


@lru_cache(maxsize=4)
def get_dataset(path: Optional[Path] = None) -> Dataset:
    """Cached dataset loader for the application runtime."""

    return load_dataset(path)


def clear_dataset_cache() -> None:
    get_dataset.cache_clear()
