"""Both backends must return the same answer shape for every question type (spec 13)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.decisions.jev_provider import JevDecisionProvider
from src.decisions.llm_provider import LlmDecisionProvider
from src.decisions.types import (
    Boolean, BooleanAnswer, Choice, ChoiceAnswer, Score, ScoreAnswer,
)
from src.llm.fake import FakeModel

QUESTIONS = {
    "b": Boolean(instructions="yes?"),
    "c": Choice(instructions="which?", criteria={"x": "ex", "y": "why"}),
    "s": Score(instructions="how much?", levels=("none", "some", "all")),
}


class _JevClient:
    def system_one(self, state, questions, **kwargs):
        return SimpleNamespace(answers={
            "b": SimpleNamespace(noul=0.6),
            "c": SimpleNamespace(choice="y", confidence=0.9, probabilities={"x": 0.1, "y": 0.9}),
            "s": SimpleNamespace(score=2.0, confidence=1.0, probabilities={0: 0.0, 1: 0.0, 2: 1.0}),
        })


def _llm():
    return LlmDecisionProvider(FakeModel(structured=[{
        "b": {"reason": "r", "probability_yes": 0.6},
        "c": {"reason": "r", "probabilities": {"x": 0.1, "y": 0.9}},
        "s": {"reason": "r", "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0}},
    }]))


@pytest.mark.parametrize("provider", [_llm(), JevDecisionProvider(_JevClient())], ids=["llm", "jev"])
def test_same_answer_shapes(provider):
    answers = provider.decide({"state": 1}, QUESTIONS)
    assert set(answers) == {"b", "c", "s"}
    assert isinstance(answers["b"], BooleanAnswer) and 0.0 <= answers["b"].probability <= 1.0
    assert isinstance(answers["c"], ChoiceAnswer) and answers["c"].choice in {"x", "y"}
    assert set(answers["c"].probabilities) == {"x", "y"} and 0.0 <= answers["c"].confidence <= 1.0
    assert isinstance(answers["s"], ScoreAnswer) and 0.0 <= answers["s"].score <= 2.0
    assert set(answers["s"].probabilities) == {0, 1, 2}
