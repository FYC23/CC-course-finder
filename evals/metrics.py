"""Accuracy, Brier score, threshold sweep and calibration for probability answers."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

DEFAULT_THRESHOLDS: tuple[float, ...] = (0.5, 0.6, 0.7, 0.8, 0.9, 0.95)


@dataclass(frozen=True)
class BinaryMetrics:
    count: int
    positives: int
    accuracy_at_half: float
    brier: float


@dataclass(frozen=True)
class ThresholdRow:
    threshold: float
    accepted: int
    precision: float | None
    recall: float | None


@dataclass(frozen=True)
class CalibrationBin:
    low: float
    high: float
    count: int
    mean_predicted: float
    observed_rate: float


@dataclass(frozen=True)
class ChoiceMetrics:
    count: int
    accuracy: float
    confusion: Mapping[tuple[str, str], int]  # (expected, predicted) -> count


def _nonempty(pairs: Sequence[object]) -> None:
    if not pairs:
        raise ValueError("no predictions to score")


def binary_metrics(pairs: Sequence[tuple[float, bool]]) -> BinaryMetrics:
    _nonempty(pairs)
    count = len(pairs)
    correct = sum((p >= 0.5) == label for p, label in pairs)
    brier = sum((p - float(label)) ** 2 for p, label in pairs) / count
    return BinaryMetrics(count=count, positives=sum(label for _, label in pairs),
                         accuracy_at_half=correct / count, brier=brier)


def threshold_sweep(
    pairs: Sequence[tuple[float, bool]], thresholds: Sequence[float] = DEFAULT_THRESHOLDS
) -> tuple[ThresholdRow, ...]:
    _nonempty(pairs)
    positives = sum(label for _, label in pairs)
    rows = []
    for threshold in thresholds:
        accepted = [label for p, label in pairs if p >= threshold]
        hits = sum(accepted)
        rows.append(ThresholdRow(
            threshold=threshold, accepted=len(accepted),
            precision=hits / len(accepted) if accepted else None,
            recall=hits / positives if positives else None,
        ))
    return tuple(rows)


def calibration(pairs: Sequence[tuple[float, bool]], bins: int = 10) -> tuple[CalibrationBin, ...]:
    _nonempty(pairs)
    out = []
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        last = index == bins - 1
        members = [(p, label) for p, label in pairs if low <= p < high or (last and p == 1.0)]
        if members:
            out.append(CalibrationBin(
                low=low, high=high, count=len(members),
                mean_predicted=sum(p for p, _ in members) / len(members),
                observed_rate=sum(label for _, label in members) / len(members),
            ))
    return tuple(out)


def choice_metrics(pairs: Sequence[tuple[str, str]]) -> ChoiceMetrics:
    _nonempty(pairs)
    correct = sum(expected == predicted for expected, predicted in pairs)
    return ChoiceMetrics(count=len(pairs), accuracy=correct / len(pairs),
                         confusion=MappingProxyType(dict(Counter(pairs))))
