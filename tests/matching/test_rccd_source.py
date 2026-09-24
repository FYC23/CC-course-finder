from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from src.matching.sources.rccd import CrosswalkRow, parse_rccd_crosswalk, seed_csv

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "matching" / "rccd_ccn_excerpt.html"


def test_parses_both_tables_with_their_section():
    rows = parse_rccd_crosswalk(_FIXTURE.read_text())
    assert rows == (
        CrosswalkRow("COM-1", "Public Speaking", "COMM-C1000", "Introduction to Public Speaking", "Currently Active"),
        CrosswalkRow("ENG-1A", "English Composition", "ENGL-C1000", "Academic Reading and Writing", "Currently Active"),
        CrosswalkRow("ENGL-1B", "Critical Thinking and Writing", "ENGL-C1003",
                     "Critical Thinking and Writing through Literature", "In Effect Summer 2026"),
        CrosswalkRow("MAT-1B", "Calculus II", "MATH-C2220", "Calculus II: Early Transcendentals",
                     "In Effect Summer 2026"),
    )


def test_page_without_rows_is_an_error():
    with pytest.raises(ValueError, match="no crosswalk rows"):
        parse_rccd_crosswalk("<html><table><tbody><tr><td>x</td></tr></tbody></table></html>")


def test_seed_csv_matches_committed_format():
    rows = parse_rccd_crosswalk(_FIXTURE.read_text())
    text = seed_csv(rows, checked_on="2026-09-23")
    parsed = list(csv.reader(io.StringIO(text)))
    assert parsed[0] == ["cc_ids", "old_code", "new_code", "source", "evidence"]
    assert parsed[4] == [
        "78 148 149", "MAT-1B", "MATH-C2220", "rccd_crosswalk",
        "rccd.edu/commoncoursenumbering: In Effect Summer 2026; checked 2026-09-23",
    ]
