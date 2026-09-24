from __future__ import annotations

from src.assist.models import AgreementRef
from src.assist.parser import parse_articulation_rows

ZWSP = "\u200b"

_REF = AgreementRef(
    target_school_id=117,
    target_school_name="University of California, Los Angeles",
    target_major="Computer Science",
    cc_id=2,
    cc_name="Evergreen Valley College",
    academic_year_id=75,
    academic_year_label="2024-2025",
    agreement_id="26089328",
    artifact_url="/api/artifacts/26089328",
)


def _pdf_text(*lines: str) -> str:
    """Join lines the way pypdf extracts newer ASSIST reports (zero-width spaces included)."""
    return "\n".join(line.replace("|", ZWSP) for line in lines)


def _pairs(raw: str) -> set[tuple[str, str]]:
    return {(row.uc_equivalent, row.course_code) for row in parse_articulation_rows(_REF, raw)}


# Layout copied from report_117_2_26089328.pdf (Evergreen Valley -> UCLA CS).
_EVERGREEN = _pdf_text(
    "NOTE: A course equivalent to UCLA's CS 31 is acceptable to meet the programming requirement.",
    "One additional course in English composition",
    "←",
    "ENGL| 001B",
    "- |English Composition (3.00)",
    "---",
    "Or",
    "---",
    "ENGL| 001C",
    "- |Critical Thinking/Composition (3.00)",
    "One course in computer programming: C++ preferred",
    "←",
    "ENGR| 050",
    "- |Introduction to Computing (4.00)",
    "COM SCI| 32",
    "- |Introduction to Computer Science II (4.00)",
    "←",
    "COMSC| 076",
    "- |Computer Science II: Introduction to Data Structures",
    "(3.00)",
    "COM SCI| 33",
    "- |Introduction to Computer Organization (5.00)",
    "←",
    "No Course Articulated",
    "COM SCI| M51A",
    "- |Logic Design of Digital Systems (4.00)",
    "←",
    "No Course Articulated",
    "MATH| 61",
    "- |Introduction to Discrete Structures (4.00)",
    "←",
    "MATH| 070",
    "- |Discrete Mathematics (4.00)",
    "---",
    "And",
    "---",
    "Select 1 Course(s) from the following",
)


def test_no_course_articulated_does_not_borrow_the_next_uc_course() -> None:
    pairs = _pairs(_EVERGREEN)
    assert not any(cc == "MATH 61" for _, cc in pairs)
    assert not any(uc in {"COM SCI 33", "COM SCI M51A"} for uc, _ in pairs)


def test_requirement_text_does_not_borrow_the_previous_cc_course() -> None:
    pairs = _pairs(_EVERGREEN)
    assert ("One course in computer programming: C++ preferred", "ENGR 050") in pairs
    assert ("One additional course in English composition", "ENGL 001B") in pairs
    assert not any(uc in {"ENGL 001C", "CS 31"} for uc, _ in pairs)


def test_uc_course_keeps_multi_word_department() -> None:
    pairs = _pairs(_EVERGREEN)
    assert ("COM SCI 32", "COMSC 076") in pairs
    assert ("MATH 61", "MATH 070") in pairs
    assert not any(uc.startswith("SCI ") for uc, _ in pairs)


def test_evergreen_excerpt_yields_exactly_the_real_articulations() -> None:
    assert _pairs(_EVERGREEN) == {
        ("One additional course in English composition", "ENGL 001B"),
        ("One course in computer programming: C++ preferred", "ENGR 050"),
        ("COM SCI 32", "COMSC 076"),
        ("MATH 61", "MATH 070"),
    }


# Layout copied from report_117_78_26089373.pdf (Riverside City -> UCLA CS): group headers
# land out of order and each CC course ends with a "Same-As:" line.
_RIVERSIDE = _pdf_text(
    "---",
    "And",
    "---",
    "Select 1 Course(s) from the following",
    "To: University of California, Los Angeles",
    "From: Riverside City College",
    "Same-As: CSC| 17C",
    "COM SCI| 31",
    "- |Introduction to Computer Science I (4.00)",
    "←",
    "CIS| 17A",
    "- |Programming Concepts and Methodology II: C++ (3.00)",
    "Same-As: CSC| 17A",
    "COM SCI| 33",
    "- |Introduction to Computer Organization (5.00)",
    "←",
    "Course(s) Denied: CIS 11;",
    "MATH| 61",
    "- |Introduction to Discrete Structures (4.00)",
    "←",
    "No Course Articulated",
    "---",
    "And",
    "---",
    "Select 1 Course(s) from the following",
)


def test_select_group_header_is_never_a_course() -> None:
    pairs = _pairs(_RIVERSIDE)
    assert not any("SELECT" in uc or "SELECT" in cc for uc, cc in pairs)


def test_denied_courses_are_not_articulations() -> None:
    pairs = _pairs(_RIVERSIDE)
    assert not any(cc == "CIS 11" for _, cc in pairs)


def test_riverside_excerpt_yields_exactly_the_real_articulations() -> None:
    assert _pairs(_RIVERSIDE) == {("COM SCI 31", "CIS 17A")}


def _single_cc_code(cc_line: str) -> str:
    raw = _pdf_text("MATH| 31A", "- |Differential and Integral Calculus (4.00)", "←", cc_line)
    (row,) = parse_articulation_rows(_REF, raw)
    return row.course_code


def test_cc_course_keeps_four_digit_numbers() -> None:
    assert _single_cc_code("MATH| 2400") == "MATH 2400"


def test_cc_course_keeps_multi_word_department() -> None:
    assert _single_cc_code("COMP SCI| 1") == "COMP SCI 1"
    assert _single_cc_code("CS/IS| 165") == "CS/IS 165"


def test_cc_course_keeps_letter_prefixed_numbers() -> None:
    assert _single_cc_code("MATH|  C285") == "MATH C285"
    assert _single_cc_code("MATH|  M25C") == "MATH M25C"


def test_cc_course_drops_nocccd_campus_marker() -> None:
    assert _single_cc_code("MATH| 151 F") == "MATH 151"
    assert _single_cc_code("PHYS| 221 C") == "PHYS 221"


def test_clean_single_spaced_lines_still_parse() -> None:
    """Lines without zero-width spaces must not be mistaken for "no course found"."""
    raw = _pdf_text("MATH 31A", "- Differential and Integral", "Calculus (4.00)", "←", "MATH 1A")
    assert ZWSP not in raw
    assert _pairs(raw) == {("MATH 31A", "MATH 1A")}


def test_inline_arrow_without_a_cc_course_is_skipped() -> None:
    assert _pairs("MATH 31B ← No Course Articulated") == set()
