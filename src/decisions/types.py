"""Question and answer types shared by every decision backend, and the provider protocol.

A backend answers named questions about one state (text or a JSON object). Answers carry
probabilities so thresholds can be set from an eval, not guessed.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, TypeVar

K = TypeVar("K", str, int)


@dataclass(frozen=True)
class Boolean:
    instructions: str


@dataclass(frozen=True)
class Choice:
    instructions: str
    criteria: Mapping[str, str]  # label -> what the label means

    def __post_init__(self) -> None:
        if len(self.criteria) < 2:
            raise ValueError("a Choice needs at least two labels")


@dataclass(frozen=True)
class Score:
    instructions: str
    levels: tuple[str, ...]  # index is the score: levels[0] is score 0

    def __post_init__(self) -> None:
        if len(self.levels) < 2:
            raise ValueError("a Score needs at least two levels")


Question = Boolean | Choice | Score


@dataclass(frozen=True)
class BooleanAnswer:
    probability: float  # probability the answer is yes


@dataclass(frozen=True)
class ChoiceAnswer:
    choice: str
    probabilities: Mapping[str, float]
    confidence: float


@dataclass(frozen=True)
class ScoreAnswer:
    score: float  # probability-weighted level; may fall between levels
    probabilities: Mapping[int, float]
    confidence: float


Answer = BooleanAnswer | ChoiceAnswer | ScoreAnswer


class DecisionUnavailable(Exception):
    """The backend could not answer (auth, network, bad output). Call sites fall back."""


class DecisionProvider(Protocol):
    name: str

    def decide(
        self, state: str | Mapping[str, object], questions: Mapping[str, Question]
    ) -> Mapping[str, Answer]: ...


def clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def normalize_probabilities(weights: Mapping[K, float]) -> Mapping[K, float]:
    clipped = {key: max(0.0, float(value)) for key, value in weights.items()}
    total = sum(clipped.values())
    if total <= 0:
        share = 1.0 / len(clipped)
        return MappingProxyType({key: share for key in clipped})
    return MappingProxyType({key: value / total for key, value in clipped.items()})


def choice_answer(probabilities: Mapping[str, float]) -> ChoiceAnswer:
    normalized = normalize_probabilities(probabilities)
    best = max(normalized, key=lambda label: normalized[label])  # first label wins ties
    return ChoiceAnswer(choice=best, probabilities=normalized, confidence=normalized[best])


def score_answer(probabilities: Mapping[int, float]) -> ScoreAnswer:
    normalized = normalize_probabilities(probabilities)
    expected = sum(level * p for level, p in normalized.items())
    return ScoreAnswer(score=expected, probabilities=normalized, confidence=max(normalized.values()))
