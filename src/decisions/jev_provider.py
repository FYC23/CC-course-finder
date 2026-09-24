"""DecisionProvider backed by Jev through ``typesafe-sdk``. The only module that imports it.

Boolean maps to Jev's Noul (probability of yes), Score levels to Score criteria. The SDK
retries 408/429/5xx itself; every SDK error becomes DecisionUnavailable.
"""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from .state import to_plain
from .types import (
    Answer, Boolean, BooleanAnswer, Choice, ChoiceAnswer, DecisionUnavailable, Question,
    ScoreAnswer, clamp01,
)


def _sdk() -> Any:
    try:
        import typesafe_sdk
    except ImportError as err:
        raise DecisionUnavailable("DECISION_PROVIDER=jev needs the SDK: uv sync --extra jev") from err
    return typesafe_sdk


def _to_sdk(sdk: Any, question: Question) -> Any:
    if isinstance(question, Boolean):
        return sdk.Noul(instructions=question.instructions)
    if isinstance(question, Choice):
        return sdk.Choice(criteria=dict(question.criteria), instructions=question.instructions)
    return sdk.Score(criteria=list(question.levels), instructions=question.instructions)


def _from_sdk(name: str, question: Question, answer: Any) -> Answer:
    try:
        if isinstance(question, Boolean):
            return BooleanAnswer(probability=clamp01(answer.noul))
        probabilities = dict(answer.probabilities)
        if isinstance(question, Choice):
            return ChoiceAnswer(
                choice=str(answer.choice),
                probabilities=MappingProxyType({str(k): clamp01(v) for k, v in probabilities.items()}),
                confidence=clamp01(answer.confidence),
            )
        return ScoreAnswer(
            score=float(answer.score),
            probabilities=MappingProxyType({int(k): clamp01(v) for k, v in probabilities.items()}),
            confidence=clamp01(answer.confidence),
        )
    except (AttributeError, TypeError, ValueError) as err:
        raise DecisionUnavailable(f"jev: unexpected answer shape for {name!r}: {err}") from err


class JevDecisionProvider:
    name = "jev"

    def __init__(self, client: Any | None = None, *, model: str | None = None) -> None:
        if client is None:
            sdk = _sdk()
            try:
                client = sdk.TypeSafeClient()
            except sdk.TypeSafeError as err:
                raise DecisionUnavailable(f"jev client: {err}") from err
        self._client = client
        self._model = model

    def decide(
        self, state: str | Mapping[str, object], questions: Mapping[str, Question]
    ) -> Mapping[str, Answer]:
        if not questions:
            raise ValueError("decide() needs at least one question")
        sdk = _sdk()
        payload = {name: _to_sdk(sdk, question) for name, question in questions.items()}
        options = {"model": self._model} if self._model else {}
        try:
            response = self._client.system_one(to_plain(state), payload, **options)
        except sdk.TypeSafeError as err:
            raise DecisionUnavailable(f"jev: {type(err).__name__}: {err}") from err
        answers = response.answers
        missing = [name for name in questions if name not in answers]
        if missing:
            raise DecisionUnavailable(f"jev: no answer for {missing[0]!r}")
        return MappingProxyType({
            name: _from_sdk(name, question, answers[name]) for name, question in questions.items()
        })
