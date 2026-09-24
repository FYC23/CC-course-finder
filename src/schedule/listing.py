"""Subject-wide course listing: every course a college lists in one subject this term.

Used only by the offline discover pass (src/matching/discover.py), never per search, so a
listing may cost a few requests per subject.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from .errors import ScheduleLookupError
from .models import CollegeScheduleSource
from .normalize import compact_code
from .term import ParsedTerm


@dataclass(frozen=True)
class ListedCourse:
    code: str
    title: str
    description: str = ""


class ListingUnsupported(ScheduleLookupError):
    """The college's schedule adapter cannot list a whole subject."""


class SubjectLister(Protocol):
    def list_subject(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, subject: str
    ) -> tuple[ListedCourse, ...]: ...


def unique_courses(courses: Iterable[ListedCourse]) -> tuple[ListedCourse, ...]:
    """One entry per course code (spellings like 'MATH-C2220' and 'MATH C2220' are one)."""
    by_code: dict[str, ListedCourse] = {}
    for course in courses:
        key = compact_code(course.code)
        if key and key not in by_code:
            by_code[key] = course
    return tuple(by_code.values())
