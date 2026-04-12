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
    80: CollegeScheduleSource(
        cc_id=80,
        cc_name="West Valley College",
        system="wvm_static",
        base_url="https://schedule.wvm.edu",
        # Shared WVM/Mission dataset: filter sections to this campus (`crns.json`).
        locations=("WV",),
    ),
}


def get_college_source(cc_id: int) -> CollegeScheduleSource:
    source = _SOURCES_BY_CC_ID.get(cc_id)
    if source is None:
        raise KeyError(f"No schedule source configured for cc_id={cc_id}")
    return source
