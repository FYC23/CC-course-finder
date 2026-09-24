from __future__ import annotations

import pytest

from src.schedule.composite import CompositeProvider
from src.schedule.listing import ListedCourse, ListingUnsupported, unique_courses
from src.schedule.models import CollegeScheduleSource
from src.schedule.term import parse_term_label

_SOURCE = CollegeScheduleSource(cc_id=1, cc_name="X", system="alpha", base_url="https://x.test", locations=())
_TERM = parse_term_label("Fall 2026")


def test_unique_courses_dedupes_spellings_first_wins():
    courses = unique_courses([
        ListedCourse("MATH-C2220", "Calculus II"), ListedCourse("MATH C2220", "dup"),
        ListedCourse("MATH-2", "Differential Equations"),
    ])
    assert [(c.code, c.title) for c in courses] == [("MATH-C2220", "Calculus II"), ("MATH-2", "Differential Equations")]


class _Searcher:
    def supports_source(self, source):
        return source.system == "alpha"


class _Lister(_Searcher):
    def list_subject(self, *, source, term, subject):
        return (ListedCourse(f"{subject} 1", "One"),)


def test_composite_dispatches_list_subject():
    composite = CompositeProvider([_Lister()])
    assert composite.list_subject(source=_SOURCE, term=_TERM, subject="MATH") == (ListedCourse("MATH 1", "One"),)


def test_composite_without_listing_support_raises():
    with pytest.raises(ListingUnsupported, match="alpha"):
        CompositeProvider([_Searcher()]).list_subject(source=_SOURCE, term=_TERM, subject="MATH")


def test_composite_unknown_system_raises_value_error():
    other = CollegeScheduleSource(cc_id=2, cc_name="Y", system="beta", base_url="https://y.test", locations=())
    with pytest.raises(ValueError, match="beta"):
        CompositeProvider([_Lister()]).list_subject(source=other, term=_TERM, subject="MATH")
