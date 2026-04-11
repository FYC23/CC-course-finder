from __future__ import annotations

from .models import CollegeScheduleSource

_SOURCES_BY_CC_ID: dict[int, CollegeScheduleSource] = {
    2: CollegeScheduleSource(
        cc_id=2,
        cc_name="Evergreen Valley College",
        system="banner",
        base_url="https://colss-prod.ec.sjeccd.edu/Student/Courses/SearchResult",
        locations=("EVC",),
    ),
    136: CollegeScheduleSource(
        cc_id=136,
        cc_name="San Jose City College",
        system="banner",
        base_url="https://colss-prod.ec.sjeccd.edu/Student/Courses/SearchResult",
        locations=("SJCC",),
    ),
}


def get_college_source(cc_id: int) -> CollegeScheduleSource:
    source = _SOURCES_BY_CC_ID.get(cc_id)
    if source is None:
        raise KeyError(f"No schedule source configured for cc_id={cc_id}")
    return source
