from __future__ import annotations

from types import MappingProxyType

import pytest

from src.schedule.replay.inputs import MissingPlaceholder, build_values, course_parts, render
from src.schedule.replay.spec import NamedInput, SpecInputs, TermInput
from src.schedule.term import TermNotListedError, parse_term_label

_FALL = parse_term_label("Fall 2026")


@pytest.mark.parametrize(
    "code,expected",
    [
        ("MATH 150AC", ("MATH", "150AC")),
        ("MATH-C2220", ("MATH", "C2220")),
        ("mat 1b", ("MAT", "1B")),
        ("CIS 17A", ("CIS", "17A")),
        ("ENGWR300", ("ENGWR", "300")),
        ("weird code 1 2", ("WEIRD CODE 1 2", "")),
    ],
)
def test_course_parts(code, expected):
    assert course_parts(code) == expected


def test_builtin_values():
    values = build_values(SpecInputs(), _FALL, "MAT 1B")
    assert values["course_code"] == "MAT 1B"
    assert values["subject"] == "MAT"
    assert values["number"] == "1B"
    assert values["term_label"] == "Fall 2026"
    assert values["yyyy"] == "2026"
    assert values["yy"] == "26"
    assert values["season"] == "fall"
    assert values["Season"] == "Fall"
    assert "term" not in values


def test_term_input_renders_format_with_season_code():
    inputs = SpecInputs(term=TermInput(format="{yy}{SEASON}", seasons=MappingProxyType({"fall": "FAL"})))
    assert build_values(inputs, _FALL, "MAT 1B")["term"] == "26FAL"


def test_term_input_season_missing_is_term_not_listed():
    inputs = SpecInputs(term=TermInput(format="{yy}{SEASON}", seasons=MappingProxyType({"spring": "SPR"})))
    with pytest.raises(TermNotListedError, match="Fall 2026"):
        build_values(inputs, _FALL, "MAT 1B")


@pytest.mark.parametrize(
    "course_code,source,transform,expected",
    [
        ("MAT 1B", "course_code", "as_is", "MAT 1B"),
        ("mat 1b", "course_code", "upper", "MAT 1B"),
        ("MAT 1B", "course_code", "dash_join", "MAT-1B"),
        ("MATH-C2220", "course_code", "dash_join", "MATH-C2220"),
        ("MAT 1B", "course_code", "compact", "MAT1B"),
        ("MAT 1B", "subject", "as_is", "MAT"),
        ("MAT 1B", "number", "as_is", "1B"),
        ("MAT 1B", "subject", "dash_join", "MAT"),
        ("MAT 1B", "subject", "compact", "MAT"),
        ("mat 1b", "number", "upper", "1B"),
    ],
)
def test_named_inputs(course_code, source, transform, expected):
    inputs = SpecInputs(named=MappingProxyType({"x": NamedInput(source=source, transform=transform)}))
    assert build_values(inputs, _FALL, course_code)["x"] == expected


def test_values_are_read_only():
    values = build_values(SpecInputs(), _FALL, "MAT 1B")
    with pytest.raises(TypeError):
        values["subject"] = "X"  # type: ignore[index]


def test_render_substitutes_and_leaves_regex_braces():
    values = {"term": "26FAL", "term_label": "Fall 2026"}
    assert render("Term eq '{term}'", values) == "Term eq '26FAL'"
    assert render(r'for="(\d{4})">\s*{term_label}', values) == r'for="(\d{4})">\s*Fall 2026'


def test_render_missing_placeholder_raises():
    with pytest.raises(MissingPlaceholder, match="token"):
        render("x={token}", {})
