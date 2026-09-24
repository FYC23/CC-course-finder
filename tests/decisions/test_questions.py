from __future__ import annotations

from src.decisions.questions import (
    COURSE_EQUIVALENT, QUESTIONS, SECTION_MODALITY, course_equivalent_state, section_modality_state,
)
from src.decisions.state import to_plain
from src.decisions.types import Boolean, Choice
from src.schedule.models import MODALITIES


def test_course_equivalent_is_boolean():
    assert isinstance(QUESTIONS[COURSE_EQUIVALENT], Boolean)


def test_section_modality_labels_are_the_modality_enum():
    question = QUESTIONS[SECTION_MODALITY]
    assert isinstance(question, Choice)
    assert tuple(question.criteria) == MODALITIES


def test_course_equivalent_state_shape():
    state = course_equivalent_state(
        college="Riverside City College", assist_code="MAT 1B", assist_title="Calculus II",
        articulates_to="MATH 31B", live_code="MATH-C2220",
        live_title="Calculus II: Early Transcendentals", live_description="A second course",
    )
    assert state == {
        "college": "Riverside City College",
        "assist_course": {"code": "MAT 1B", "title": "Calculus II", "articulates_to": "MATH 31B"},
        "live_course": {"code": "MATH-C2220", "title": "Calculus II: Early Transcendentals",
                        "description": "A second course"},
    }


def test_long_descriptions_are_trimmed():
    state = course_equivalent_state(
        college="c", assist_code="a", assist_title="t", articulates_to="u",
        live_code="l", live_title="lt", live_description="x" * 5000,
    )
    assert len(state["live_course"]["description"]) == 1200


def test_section_modality_state_shape():
    state = section_modality_state(
        raw_tokens=("Dist. Ed Internet Delayed",), locations=("Online Class",), has_timed_meetings=False,
    )
    assert to_plain(state) == {"raw_modality_tokens": ["Dist. Ed Internet Delayed"],
                               "meeting_locations": ["Online Class"], "has_timed_meetings": False}
