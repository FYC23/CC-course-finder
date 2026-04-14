from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby

from src.assist.models import ArticulationRow
from src.schedule.models import CourseAvailability, ParsedSection


@dataclass(frozen=True)
class SearchResult:
    cc_name: str
    cc_id: int
    course_code: str
    course_title: str
    uc_equivalent: str
    target_requirements: list[str]
    offered_this_term: bool | None
    sections: list[ParsedSection]
    schedule_source_url: str
    source_url: str
    academic_year: str
    agreement_id: str


def join_results(
    artic_rows: list[ArticulationRow],
    schedule_results: list[CourseAvailability],
) -> list[SearchResult]:
    # Index schedule results by (cc_id, course_code) for O(1) lookup
    sched_index: dict[tuple[int, str], CourseAvailability] = {
        (r.cc_id, r.course_code): r for r in schedule_results
    }

    # Group artic rows by (cc_id, course_code) to collapse requirements
    results: list[SearchResult] = []
    sorted_rows = sorted(artic_rows, key=lambda r: (r.cc_id, r.course_code))
    for (cc_id, course_code), group in groupby(sorted_rows, key=lambda r: (r.cc_id, r.course_code)):
        rows = list(group)
        first = rows[0]
        requirements = list(dict.fromkeys(r.target_requirement for r in rows))

        avail = sched_index.get((cc_id, course_code))
        if avail is None:
            offered: bool | None = None
            sections: list[ParsedSection] = []
            schedule_source_url = ""
        else:
            offered = avail.offered
            sections = avail.sections
            schedule_source_url = avail.source_url

        results.append(SearchResult(
            cc_name=first.cc_name,
            cc_id=cc_id,
            course_code=course_code,
            course_title=first.course_title,
            uc_equivalent=first.uc_equivalent,
            target_requirements=requirements,
            offered_this_term=offered,
            sections=sections,
            schedule_source_url=schedule_source_url,
            source_url=first.source_url,
            academic_year=first.academic_year,
            agreement_id=first.agreement_id,
        ))

    return results
