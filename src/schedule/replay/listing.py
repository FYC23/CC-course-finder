"""Turn a listing run's bodies into ListedCourse entries (see spec.ListingSpec)."""
from __future__ import annotations

from collections.abc import Sequence

from ..listing import ListedCourse, unique_courses
from .extractor import html_rows, json_rows, text_of
from .spec import ListingExtract


def extract_listing(bodies: Sequence[str], extract: ListingExtract) -> tuple[ListedCourse, ...]:
    courses: list[ListedCourse] = []
    for body in bodies:
        rows = (
            json_rows(body, extract.rows)
            if extract.kind == "json"
            else html_rows(body, extract.rows, extract.marker)
        )
        for row in rows:
            code = text_of(row, extract.code).strip()
            if not code:
                continue
            description = text_of(row, extract.description).strip() if extract.description else ""
            courses.append(ListedCourse(code=code, title=text_of(row, extract.title).strip(),
                                        description=description))
    return unique_courses(courses)
