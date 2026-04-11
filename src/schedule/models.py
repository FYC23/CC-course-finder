from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CollegeScheduleSource:
    cc_id: int
    cc_name: str
    system: str
    base_url: str
    locations: tuple[str, ...]


@dataclass(frozen=True)
class ParsedSection:
    section_id: str
    status: str
    modality: str
    title: str
    instructor: str


@dataclass(frozen=True)
class CourseAvailability:
    cc_id: int
    cc_name: str
    term: str
    course_code: str
    offered: bool
    sections: list[ParsedSection]
    source_url: str
    raw_summary: str = ""
