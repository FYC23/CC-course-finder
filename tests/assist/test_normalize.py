from __future__ import annotations

from src.assist.models import AgreementRef
from src.assist.normalize import dedupe_rows, filter_empty_course_codes
from src.assist.parser import parse_articulation_rows


def test_parse_articulation_rows_detects_arrow_pairs() -> None:
    ref = AgreementRef(
        target_school_id=11,
        target_school_name="University of California, Los Angeles",
        target_major="Computer Science",
        cc_id=54,
        cc_name="De Anza College",
        academic_year_id=75,
        academic_year_label="2024-2025",
        agreement_id="12345678",
        artifact_url="/api/artifacts/12345678",
    )
    raw = """
    Lower-Division requirements
    MATH 31B ← MATH 1B Calculus II
    CS 31 -> CIS 22A Introduction to Programming
    """
    rows = parse_articulation_rows(ref, raw)
    rows = filter_empty_course_codes(dedupe_rows(rows))
    assert len(rows) == 2
    assert rows[0].uc_equivalent == "MATH 31B"
    assert rows[0].course_code == "MATH 1B"
    assert rows[1].uc_equivalent == "CS 31"
    assert rows[1].course_code == "CIS 22A"

