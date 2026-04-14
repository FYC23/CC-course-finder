from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.assist.models import ArticulationRow
from src.schedule.models import CourseAvailability, ParsedSection
from src.web.join import SearchResult, join_results


@dataclass(frozen=True)
class F:
    """Helper: minimal ArticulationRow for tests."""
    cc_id: int
    course_code: str
    cc_name: str = "Test CC"
    target_school: str = "UCLA"
    target_major: str = "Computer Science"
    target_requirement: str = "Area A"
    uc_equivalent: str = "COM SCI 1"
    course_title: str = "Intro CS"
    agreement_id: str = "123"
    academic_year: str = "2024-2025"
    source_url: str = "https://assist.org/123"
    notes: str = ""
    raw_text: str = ""

    def row(self) -> ArticulationRow:
        return ArticulationRow(
            target_school=self.target_school,
            target_major=self.target_major,
            target_requirement=self.target_requirement,
            uc_equivalent=self.uc_equivalent,
            cc_name=self.cc_name,
            cc_id=self.cc_id,
            course_code=self.course_code,
            course_title=self.course_title,
            agreement_id=self.agreement_id,
            academic_year=self.academic_year,
            source_url=self.source_url,
            notes=self.notes,
            raw_text=self.raw_text,
        )


def avail(
    cc_id: int,
    course_code: str,
    offered: bool = True,
    sections: list[ParsedSection] | None = None,
) -> CourseAvailability:
    return CourseAvailability(
        cc_id=cc_id,
        cc_name="Test CC",
        term="Spring 2026",
        course_code=course_code,
        offered=offered,
        sections=sections or [],
        source_url="https://example.com",
    )


class TestJoinResults:
    def test_happy_path(self) -> None:
        artic_rows = [
            F(cc_id=2, course_code="CS 49", cc_name="EVC", uc_equivalent="COM SCI 49",
              target_requirement="Area C").row(),
        ]
        schedule_results = [
            avail(cc_id=2, course_code="CS 49", offered=True),
        ]
        results = join_results(artic_rows, schedule_results)
        assert len(results) == 1
        r = results[0]
        assert r.cc_id == 2
        assert r.course_code == "CS 49"
        assert r.offered_this_term is True
        assert r.target_requirements == ["Area C"]

    def test_multi_requirement(self) -> None:
        artic_rows = [
            F(cc_id=2, course_code="MATH 1B", target_requirement="Area A").row(),
            F(cc_id=2, course_code="MATH 1B", target_requirement="Area B").row(),
        ]
        results = join_results(artic_rows, [])
        assert len(results) == 1
        assert set(results[0].target_requirements) == {"Area A", "Area B"}

    def test_cc_not_in_catalog(self) -> None:
        artic_rows = [
            F(cc_id=99, course_code="CS 10", cc_name="Unknown CC").row(),
        ]
        results = join_results(artic_rows, [])
        assert len(results) == 1
        assert results[0].offered_this_term is None
        assert results[0].sections == []

    def test_no_schedule_result(self) -> None:
        artic_rows = [
            F(cc_id=2, course_code="CS 49", cc_name="EVC").row(),
        ]
        results = join_results(artic_rows, [])
        assert len(results) == 1
        assert results[0].offered_this_term is None
        assert results[0].sections == []

    def test_multiple_ccs(self) -> None:
        artic_rows = [
            F(cc_id=2, course_code="CS 49", cc_name="EVC").row(),
            F(cc_id=80, course_code="CS 49", cc_name="WVC").row(),
        ]
        results = join_results(artic_rows, [
            avail(cc_id=2, course_code="CS 49", offered=True),
        ])
        assert len(results) == 2
        evc = next(r for r in results if r.cc_id == 2)
        wvc = next(r for r in results if r.cc_id == 80)
        assert evc.offered_this_term is True
        assert wvc.offered_this_term is None

    def test_sections_preserved(self) -> None:
        sections = [
            ParsedSection(
                section_id="001",
                status="Open",
                modality="Online",
                title="LEC A",
                instructor="Dr. Smith",
            ),
        ]
        artic_rows = [F(cc_id=2, course_code="CS 49").row()]
        results = join_results(artic_rows, [avail(cc_id=2, course_code="CS 49", sections=sections)])
        assert len(results[0].sections) == 1
        assert results[0].sections[0].section_id == "001"
