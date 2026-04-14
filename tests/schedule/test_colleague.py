from __future__ import annotations

from src.schedule.colleague import (
    CourseIdentity,
    course_matches,
    normalize_modality,
    normalize_status,
    parse_course_identity,
    parse_requested_course,
)


def test_parse_requested_course_accepts_space_format():
    parsed = parse_requested_course("MATH 115")
    assert parsed == CourseIdentity(subject="MATH", number="115")


def test_parse_requested_course_normalizes_leading_zero():
    parsed = parse_requested_course("MATH 0115")
    assert parsed == CourseIdentity(subject="MATH", number="115")


def test_parse_course_identity_returns_none_for_invalid_text():
    assert parse_course_identity("Calculus II") is None


def test_course_matches_uses_subject_and_number():
    requested = parse_requested_course("STAT C1000")
    assert course_matches(requested, "STAT C1000 - Introduction to Statistics")
    assert not course_matches(requested, "MATH C1000 - Introduction to Statistics")


def test_normalize_status_maps_common_values():
    assert normalize_status("Open") == "open"
    assert normalize_status("Closed") == "closed"
    assert normalize_status("Something Else") == "unknown"


def test_normalize_modality_uses_campus_and_type_text():
    assert normalize_modality(campus="Hybrid", section_type="CLAS") == "hybrid"
    assert normalize_modality(campus="Kentfield", section_type="Web Based") == "online"
    assert normalize_modality(campus="Kentfield", section_type="CLAS") == "in_person"
