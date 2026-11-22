from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import DatasetError
from app.services.dataset import load_dataset

HEADER = (
    "exercise_id,exercise_name,body_part,equipment,primary_muscle,"
    "secondary_muscle,exercise_type,movement_type,exercise_image\n"
)


def _write(tmp_path: Path, rows: str) -> Path:
    path = tmp_path / "dataset.csv"
    path.write_text(HEADER + rows, encoding="utf-8")
    return path


@pytest.mark.unit
def test_loads_valid_dataset(tmp_path):
    path = _write(
        tmp_path,
        "1,bench press,chest,barbell,pectoralis major,triceps,weight_reps,compound,http://img\n"
        "2,squat,quadriceps,barbell,rectus femoris,glutes,weight_reps,compound,http://img\n",
    )
    dataset = load_dataset(path)
    assert len(dataset.exercises) == 2
    assert len(dataset.version) == 16
    assert dataset.exercises[0].body_part.value == "chest"
    assert dataset.exercises[0].equipment[0].value == "barbell"


@pytest.mark.unit
def test_duplicate_id_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        "1,bench press,chest,barbell,pectorals,,weight_reps,compound,http://img\n"
        "1,squat,quadriceps,barbell,quads,,weight_reps,compound,http://img\n",
    )
    with pytest.raises(DatasetError, match="exercise_id duplikat"):
        load_dataset(path)


@pytest.mark.unit
def test_duplicate_name_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        "1,Bench Press,chest,barbell,pectorals,,weight_reps,compound,http://img\n"
        "2,bench press,back,barbell,lats,,weight_reps,compound,http://img\n",
    )
    with pytest.raises(DatasetError, match="exercise_name duplikat"):
        load_dataset(path)


@pytest.mark.unit
def test_unknown_body_part_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        "1,bench press,unknown,barbell,pectorals,,weight_reps,compound,http://img\n",
    )
    with pytest.raises(DatasetError, match="body_part"):
        load_dataset(path)


@pytest.mark.unit
def test_unknown_movement_type_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        "1,bench press,chest,barbell,pectorals,,weight_reps,stretch,http://img\n",
    )
    with pytest.raises(DatasetError, match="movement_type"):
        load_dataset(path)


@pytest.mark.unit
def test_missing_column_is_rejected(tmp_path):
    path = tmp_path / "dataset.csv"
    path.write_text("exercise_id,exercise_name\n1,bench\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="Kolom dataset tidak lengkap"):
        load_dataset(path)


@pytest.mark.unit
def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(DatasetError, match="tidak ditemukan"):
        load_dataset(tmp_path / "missing.csv")
