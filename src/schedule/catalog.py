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
        locations=("WVC",),
    ),
}


def get_college_source(cc_id: int) -> CollegeScheduleSource:
    source = _SOURCES_BY_CC_ID.get(cc_id)
    if source is None:
        raise KeyError(f"No schedule source configured for cc_id={cc_id}")
    return source


def find_college_source_by_name(name: str) -> CollegeScheduleSource:
    """Case-insensitive substring match. Raises KeyError if 0 or >1 matches."""
    needle = name.strip().lower()
    matches = [
        s for s in _SOURCES_BY_CC_ID.values()
        if needle in s.cc_name.lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) == 0:
        raise KeyError(f"No schedule source matches name={name!r}")
    names = ", ".join(f"{s.cc_name!r} (cc_id={s.cc_id})" for s in matches)
    raise KeyError(f"Ambiguous name {name!r} matches: {names}")
