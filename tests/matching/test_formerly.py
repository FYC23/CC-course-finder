from __future__ import annotations

import json
from pathlib import Path

from src.matching.formerly import formerly_aliases, formerly_pairs
from src.schedule.colleague_listing import parse_catalog_listing
from src.schedule.listing import ListedCourse

_CATALOG = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "colleague" / "fcc_math_catalog.json").read_text()
)


def test_bare_note_refers_to_the_course_itself_even_misspelled():
    course = ListedCourse("MATH C2210", "CALCULUS I", "placement ... process. (Fomerly MATH 5A) (C-ID MATH 210)")
    assert formerly_pairs(course) == (("MATH 5A", "MATH C2210", "(Fomerly MATH 5A)"),)


def test_note_after_another_code_refers_to_that_code():
    course = ListedCourse("MATH 211S", "SUPPORT 4 STATS", "Corequisite: STAT C1000 (formerly MATH 11) or MATH 42.")
    assert formerly_pairs(course) == (("MATH 11", "STAT C1000", "STAT C1000 (formerly MATH 11)"),)


def test_words_that_are_not_codes_are_ignored():
    assert formerly_pairs(ListedCourse("X 1", "t", "(formerly known as Algebra)")) == ()


def test_fresno_catalog_yields_three_verified_aliases():
    aliases = formerly_aliases(35, parse_catalog_listing(_CATALOG))
    assert {(a.old_code, a.new_code) for a in aliases} == {
        ("MATH 11", "STAT C1000"), ("MATH 5A", "MATH C2210"), ("MATH 5B", "MATH C2220"),
    }
    assert all(a.status == "verified" and a.source == "catalog_formerly" and a.cc_id == 35 for a in aliases)
    assert any(a.evidence.startswith("MATH C2220 catalog: (Formerly MATH 5B)") for a in aliases)
