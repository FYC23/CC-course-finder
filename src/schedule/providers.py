from __future__ import annotations

from typing import Protocol

from .models import CollegeScheduleSource, CourseAvailability
from .term import ParsedTerm


class ScheduleProvider(Protocol):
    def search_course(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, course_code: str
    ) -> CourseAvailability: ...
