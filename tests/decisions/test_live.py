"""Live decision call; runs only with RUN_LIVE_DECISIONS=1 and a configured provider."""
from __future__ import annotations

import os

import pytest

from src.decisions.factory import decision_provider_from_env
from src.decisions.questions import COURSE_EQUIVALENT, QUESTIONS, course_equivalent_state
from src.decisions.types import BooleanAnswer

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_DECISIONS") != "1", reason="live decision calls are opt-in"
)


def test_live_provider_answers_course_equivalent():
    provider = decision_provider_from_env()
    assert provider is not None, "set DECISION_PROVIDER=llm or jev for the live test"
    state = course_equivalent_state(
        college="Riverside City College", assist_code="MAT 1B", assist_title="Calculus II",
        articulates_to="MATH 31B", live_code="MATH-C2220",
        live_title="Calculus II: Early Transcendentals",
        live_description="A second course in differential and integral calculus of a single variable.",
    )
    answer = provider.decide(state, {COURSE_EQUIVALENT: QUESTIONS[COURSE_EQUIVALENT]})[COURSE_EQUIVALENT]
    assert isinstance(answer, BooleanAnswer) and answer.probability > 0.5
