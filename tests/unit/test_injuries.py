from __future__ import annotations

import pytest

from app.core.errors import UnknownInjuryError
from app.domain.constants import BodyPart
from app.domain.injuries import map_injury_to_body_parts


@pytest.mark.unit
def test_body_part_is_mapped_to_itself():
    assert map_injury_to_body_parts(["chest"]) == {BodyPart.CHEST}


@pytest.mark.unit
def test_muscle_name_is_mapped_to_body_part():
    assert map_injury_to_body_parts(["pectoralis major"]) == {BodyPart.CHEST}
    assert map_injury_to_body_parts(["rectus femoris"]) == {BodyPart.QUADRICEPS}


@pytest.mark.unit
def test_knee_maps_to_conservative_leg_parts():
    mapped = map_injury_to_body_parts(["knee"])
    assert mapped == {
        BodyPart.QUADRICEPS,
        BodyPart.HAMSTRINGS,
        BodyPart.GLUTES,
        BodyPart.CALVES,
    }


@pytest.mark.unit
def test_lower_back_maps_to_posterior_chain():
    mapped = map_injury_to_body_parts(["lower back"])
    assert mapped == {BodyPart.BACK, BodyPart.GLUTES, BodyPart.HAMSTRINGS}


@pytest.mark.unit
def test_case_and_separator_normalisation():
    assert map_injury_to_body_parts(["LOWER-BACK"]) == map_injury_to_body_parts(
        ["lower back"]
    )
    assert map_injury_to_body_parts(["Knee"]) == map_injury_to_body_parts(["knee"])


@pytest.mark.unit
def test_unknown_injury_is_rejected():
    with pytest.raises(UnknownInjuryError) as exc_info:
        map_injury_to_body_parts(["broken_soul"])
    assert "broken_soul" in str(exc_info.value)
    assert exc_info.value.code == "unknown_injury"


@pytest.mark.unit
def test_empty_injuries_are_safe():
    assert map_injury_to_body_parts([]) == set()
    assert map_injury_to_body_parts(["", "  "]) == set()
