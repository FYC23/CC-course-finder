from __future__ import annotations

import pytest

from src.schedule.term import ParsedTerm, parse_term_label, term_match_rank


@pytest.mark.parametrize(
    ("label", "season", "year"),
    [
        ("Summer 2026", "summer", 2026),
        ("Fall 2026", "fall", 2026),
        ("Spring 2027", "spring", 2027),
    ],
)
def test_parse_term_label_valid(label: str, season: str, year: int) -> None:
    parsed = parse_term_label(label)
    assert parsed == ParsedTerm(label=label, season=season, year=year)


@pytest.mark.parametrize(
    "label",
    [
        "2026 Summer",
        "summer 2026",
        "Winter 2026",
        "Summer2026",
        "",
    ],
)
def test_parse_term_label_invalid(label: str) -> None:
    with pytest.raises(ValueError):
        parse_term_label(label)


@pytest.mark.parametrize(
    ("label", "description", "expected_rank"),
    [
        ("Fall 2026", "Fall 2026", 0),
        ("Fall 2026", "fall  2026", 0),
        ("Fall 2026", "Fall 2026 Regular", 1),
        ("Summer 2026", "Summer 2026-CONT.ED.", 2),
        (
            "Fall 2026",
            "Fall Term 2026 202710 12-AUG-2026 - 09-DEC-2026",
            3,
        ),
        ("Fall 2026", "Fall Semester 2026", 3),
        ("Fall 2026", "2026 Fall Semester", 3),
        ("Fall 2026", "Spring 2026", None),
        ("Fall 2026", "Fall 20260", None),
    ],
)
def test_term_match_rank(label: str, description: str, expected_rank: int | None) -> None:
    term = parse_term_label(label)
    assert term_match_rank(term, description) == expected_rank
