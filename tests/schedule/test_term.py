from __future__ import annotations

import pytest

from src.schedule.term import ParsedTerm, parse_term_label


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
