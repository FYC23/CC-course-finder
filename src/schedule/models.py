from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, time
from types import MappingProxyType

DAY_CODES: tuple[str, ...] = ("M", "T", "W", "R", "F", "S", "U")
MODALITIES: tuple[str, ...] = ("async_online", "sync_online", "hybrid", "in_person", "unknown")
STATUSES: tuple[str, ...] = ("open", "closed", "waitlist", "unknown")
CATALOG_STATUSES: tuple[str, ...] = ("active", "stale", "unsupported")
DEFAULT_CAMPUS_TZ = "America/Los_Angeles"


def _empty_params() -> Mapping[str, str]:
    return MappingProxyType({})


@dataclass(frozen=True)
class CollegeScheduleSource:
    cc_id: int
    cc_name: str
    system: str
    base_url: str
    locations: tuple[str, ...]
    params: Mapping[str, str] = field(default_factory=_empty_params, compare=False, hash=False)
    status: str = "active"


@dataclass(frozen=True)
class Meeting:
    """One recurring meeting block of a section. Times are campus-local."""

    days: tuple[str, ...] = ()
    start_local: time | None = None
    end_local: time | None = None
    timezone: str = DEFAULT_CAMPUS_TZ
    location: str = ""
    is_online: bool = False
    start_date: date | None = None
    end_date: date | None = None

    @property
    def is_timed(self) -> bool:
        return self.start_local is not None and self.end_local is not None


@dataclass(frozen=True)
class ParsedSection:
    section_id: str
    status: str
    modality: str
    title: str
    instructor: str
    meetings: tuple[Meeting, ...] = ()
    seats_total: int | None = None
    seats_used: int | None = None
    course_code_as_listed: str = ""


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
