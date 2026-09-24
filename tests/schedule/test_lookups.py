from __future__ import annotations

import requests

from src.matching.resolve import LiveCode
from src.schedule.lookups import Attempt, merge_attempts
from src.schedule.models import CollegeScheduleSource, CourseAvailability, ParsedSection
from src.schedule.term import parse_term_label

_SOURCE = CollegeScheduleSource(cc_id=78, cc_name="Riverside City College", system="replay",
                                base_url="https://x.test", locations=())
_TERM = parse_term_label("Fall 2026")
_ALIAS = LiveCode("MATH-C2220", "rccd_crosswalk", "verified")
_RENAME = LiveCode("MATH 1B", "rccd_live_listing", "verified")
_ORIGINAL = LiveCode("MAT 1B")


def _section(section_id, code):
    return ParsedSection(section_id=section_id, status="open", modality="unknown", title="Calculus II",
                         instructor="", course_code_as_listed=code)


def _found(code, *sections, summary="ok"):
    return CourseAvailability(cc_id=78, cc_name="Riverside City College", term="Fall 2026", course_code=code,
                              offered=bool(sections), sections=list(sections), source_url=f"https://x.test/{code}",
                              raw_summary=summary)


def _merge(*attempts):
    return merge_attempts(source=_SOURCE, term=_TERM, course_code="MAT 1B", attempts=attempts)


def test_single_lookup_under_assist_code_is_returned_unchanged():
    availability = _found("MAT 1B", _section("1", "MAT-1B"))
    assert _merge(Attempt(_ORIGINAL, availability=availability)) == availability


def test_alias_hit_is_offered_under_the_assist_code_and_says_how():
    result = _merge(
        Attempt(_ALIAS, availability=_found("MATH-C2220", _section("11", "MATH-C2220"), summary="1 section")),
        Attempt(_RENAME, availability=_found("MATH 1B", summary="0 sections")),
        Attempt(_ORIGINAL, availability=_found("MAT 1B", summary="0 sections")),
    )
    assert (result.course_code, result.offered, [s.section_id for s in result.sections]) == ("MAT 1B", True, ["11"])
    assert (result.matched_code, result.match_source, result.match_status) == (
        "MATH-C2220", "rccd_crosswalk", "verified",
    )
    assert result.source_url == "https://x.test/MATH-C2220"
    assert result.raw_summary == "MATH-C2220: 1 section | MATH 1B: 0 sections | MAT 1B: 0 sections"


def test_sections_are_pooled_without_duplicates():
    both = _section("11", "MATH-C2220")
    result = _merge(
        Attempt(_ALIAS, availability=_found("MATH-C2220", both)),
        Attempt(_ORIGINAL, availability=_found("MAT 1B", both, _section("12", "MAT-1B"))),
    )
    assert [(s.course_code_as_listed, s.section_id) for s in result.sections] == [
        ("MATH-C2220", "11"), ("MAT-1B", "12"),
    ]


def test_hit_only_under_assist_code_records_no_alias():
    result = _merge(
        Attempt(_ALIAS, availability=_found("MATH-C2220")),
        Attempt(_ORIGINAL, availability=_found("MAT 1B", _section("5", "MAT-1B"))),
    )
    assert result.offered and result.matched_code == ""


def test_any_failure_without_a_hit_is_could_not_check():
    result = _merge(
        Attempt(_ALIAS, availability=_found("MATH-C2220")),
        Attempt(_ORIGINAL, error=requests.Timeout("slow")),
    )
    assert result.lookup_error == "The college's schedule server took too long to answer."
    assert result.course_code == "MAT 1B" and not result.offered


def test_no_hits_and_no_failures_is_not_offered():
    result = _merge(Attempt(_ALIAS, availability=_found("MATH-C2220")),
                    Attempt(_ORIGINAL, availability=_found("MAT 1B")))
    assert (result.course_code, result.offered, result.lookup_error, result.matched_code) == ("MAT 1B", False, None, "")


def test_skipped_failure_says_so():
    err = requests.ConnectionError("down")
    result = _merge(Attempt(_ALIAS, error=err, skipped=True))
    assert result.raw_summary.startswith("[skipped: college unreachable")
