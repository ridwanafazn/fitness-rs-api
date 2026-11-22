"""Injury-to-body-part mapping.

The public API accepts common human terms (``knee``, ``lower back``, ``ACL``)
and converts them into the body parts the recommender understands.  Unknown
terms are rejected instead of silently ignored: silently dropping an injury is
the most dangerous failure mode for a fitness recommender.
"""

from __future__ import annotations

from typing import Iterable, List, Set

from app.core.errors import UnknownInjuryError
from app.domain.constants import (
    INJURY_ALIASES,
    MUSCLE_TO_BODY_PART,
    BodyPart,
    normalise_injury_token,
    supported_injury_terms,
)


def map_injury_to_body_parts(injuries: Iterable[str]) -> Set[BodyPart]:
    """Return every body part that should be avoided for the given injuries.

    Raises:
        UnknownInjuryError: if any term is not part of the supported vocabulary.
    """

    mapped: Set[BodyPart] = set()
    unknown: List[str] = []

    for raw in injuries:
        term = normalise_injury_token(raw)
        if not term:
            continue
        if term in INJURY_ALIASES:
            mapped.update(INJURY_ALIASES[term])
            continue
        if term in MUSCLE_TO_BODY_PART:
            mapped.add(MUSCLE_TO_BODY_PART[term])
            continue
        try:
            mapped.add(BodyPart(term))
        except ValueError:
            unknown.append(raw)

    if unknown:
        examples = ", ".join(sorted(supported_injury_terms())[:20])
        raise UnknownInjuryError(
            f"Nama cedera tidak dikenali: {', '.join(unknown)}.",
            details={
                "unknown_terms": unknown,
                "supported_examples": examples,
                "hint": (
                    "Gunakan body part (chest, back, shoulders), nama otot "
                    "(pectoralis major), atau istilah umum (knee, lower back, "
                    "elbow, wrist)."
                ),
            },
        )

    return mapped
