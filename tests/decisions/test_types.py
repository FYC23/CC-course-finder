from __future__ import annotations

from types import MappingProxyType

import pytest

from src.decisions.state import to_plain
from src.decisions.types import (
    Choice, Score, choice_answer, normalize_probabilities, score_answer,
)


def test_normalize_clips_negatives_and_sums_to_one():
    assert normalize_probabilities({"a": 3.0, "b": 1.0, "c": -2.0}) == {"a": 0.75, "b": 0.25, "c": 0.0}


def test_normalize_all_zero_is_uniform():
    assert normalize_probabilities({"a": 0.0, "b": 0.0}) == {"a": 0.5, "b": 0.5}


def test_choice_answer_picks_most_likely_first_on_ties():
    answer = choice_answer({"x": 0.4, "y": 0.4, "z": 0.2})
    assert (answer.choice, answer.confidence) == ("x", 0.4)


def test_score_answer_is_expected_level():
    answer = score_answer({0: 0.0, 1: 0.5, 2: 0.5})
    assert (answer.score, answer.confidence) == (1.5, 0.5)


def test_choice_needs_two_labels():
    with pytest.raises(ValueError, match="at least two"):
        Choice(instructions="i", criteria=MappingProxyType({"only": "one"}))


def test_score_needs_two_levels():
    with pytest.raises(ValueError, match="at least two"):
        Score(instructions="i", levels=("low",))


def test_to_plain_unwraps_proxies_and_tuples():
    value = MappingProxyType({"a": (1, MappingProxyType({"b": None}))})
    assert to_plain(value) == {"a": [1, {"b": None}]}
