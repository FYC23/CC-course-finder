from __future__ import annotations

from types import SimpleNamespace

import pytest
import typesafe_sdk

from src.decisions.jev_provider import JevDecisionProvider
from src.decisions.types import (
    Boolean, BooleanAnswer, Choice, ChoiceAnswer, DecisionUnavailable, Score, ScoreAnswer,
)


class _Client:
    def __init__(self, answers=None, error=None):
        self._answers = answers or {}
        self._error = error
        self.calls = []

    def system_one(self, state, questions, **kwargs):
        self.calls.append((state, questions, kwargs))
        if self._error is not None:
            raise self._error
        return SimpleNamespace(answers=self._answers)


_QUESTIONS = {
    "same": Boolean(instructions="same course?"),
    "mode": Choice(instructions="how taught?", criteria={"online": "web", "campus": "room"}),
    "fit": Score(instructions="how good?", levels=("bad", "ok", "good")),
}


def test_questions_map_to_sdk_types():
    client = _Client(answers={
        "same": SimpleNamespace(noul=0.8),
        "mode": SimpleNamespace(choice="online", confidence=0.7, probabilities={"online": 0.7, "campus": 0.3}),
        "fit": SimpleNamespace(score=1.4, confidence=0.6, probabilities={0: 0.1, 1: 0.4, 2: 0.5}),
    })
    JevDecisionProvider(client).decide({"k": (1, 2)}, _QUESTIONS)
    state, sent, kwargs = client.calls[0]
    assert state == {"k": [1, 2]} and kwargs == {}
    assert isinstance(sent["same"], typesafe_sdk.Noul) and sent["same"].instructions == "same course?"
    assert isinstance(sent["mode"], typesafe_sdk.Choice) and sent["mode"].criteria == {"online": "web", "campus": "room"}
    assert isinstance(sent["fit"], typesafe_sdk.Score) and list(sent["fit"].criteria) == ["bad", "ok", "good"]


def test_answers_map_back_to_shared_types():
    client = _Client(answers={
        "same": SimpleNamespace(noul=0.8),
        "mode": SimpleNamespace(choice="online", confidence=0.7, probabilities={"online": 0.7, "campus": 0.3}),
        "fit": SimpleNamespace(score=1.4, confidence=0.6, probabilities={0: 0.1, 1: 0.4, 2: 0.5}),
    })
    answers = JevDecisionProvider(client).decide("text state", _QUESTIONS)
    assert answers["same"] == BooleanAnswer(probability=0.8)
    assert isinstance(answers["mode"], ChoiceAnswer) and answers["mode"].choice == "online"
    assert isinstance(answers["fit"], ScoreAnswer) and answers["fit"].score == 1.4
    assert dict(answers["fit"].probabilities) == {0: 0.1, 1: 0.4, 2: 0.5}


def test_model_override_is_passed():
    client = _Client(answers={"same": SimpleNamespace(noul=0.5)})
    JevDecisionProvider(client, model="jev-latest").decide("s", {"same": _QUESTIONS["same"]})
    assert client.calls[0][2] == {"model": "jev-latest"}


def test_sdk_error_is_decision_unavailable():
    client = _Client(error=typesafe_sdk.TypeSafeError("boom"))
    with pytest.raises(DecisionUnavailable, match="boom"):
        JevDecisionProvider(client).decide("s", {"same": _QUESTIONS["same"]})


def test_missing_answer_is_decision_unavailable():
    with pytest.raises(DecisionUnavailable, match="no answer for 'same'"):
        JevDecisionProvider(_Client(answers={})).decide("s", {"same": _QUESTIONS["same"]})


def test_wrong_answer_shape_is_decision_unavailable():
    client = _Client(answers={"same": SimpleNamespace(choice="x")})
    with pytest.raises(DecisionUnavailable, match="unexpected answer shape"):
        JevDecisionProvider(client).decide("s", {"same": _QUESTIONS["same"]})


def test_missing_api_key_is_decision_unavailable(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(DecisionUnavailable, match="jev client"):
        JevDecisionProvider()
