"""Classify whether a section's meeting times work for a student in another timezone."""
from __future__ import annotations

from datetime import date, datetime, time
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones

from .models import Meeting, ParsedSection

FIT_ASYNC = "async"
FIT_FITS = "fits"
FIT_CONFLICTS = "conflicts"
FIT_UNKNOWN = "unknown"


@lru_cache(maxsize=1)
def _known_timezones() -> frozenset[str]:
    return frozenset(available_timezones())


def is_known_timezone(name: str) -> bool:
    """True only for names in the IANA timezone database (e.g. "Asia/Shanghai")."""
    return name in _known_timezones()


def to_student_local(
    campus_time: time, on_date: date, campus_tz: str, student_tz: str
) -> tuple[time, int]:
    """Return (student-local time, day shift) for a campus-local clock time on a date.

    Both zones are IANA names, so daylight saving on either side is applied for that date.
    """
    campus_dt = datetime.combine(on_date, campus_time, tzinfo=ZoneInfo(campus_tz))
    student_dt = campus_dt.astimezone(ZoneInfo(student_tz))
    day_shift = (student_dt.date() - on_date).days
    return student_dt.time().replace(tzinfo=None), day_shift


def _fits_on_date(
    start_local: time,
    end_local: time,
    on_date: date,
    campus_tz: str,
    *,
    student_tz: str,
    window_start_hour: int,
    window_end_hour: int,
) -> bool:
    start, start_shift = to_student_local(start_local, on_date, campus_tz, student_tz)
    end, end_shift = to_student_local(end_local, on_date, campus_tz, student_tz)
    if start_shift != end_shift:
        return False
    window_start = time(window_start_hour, 0)
    window_end = time(window_end_hour, 0) if window_end_hour < 24 else time(23, 59, 59)
    return window_start <= start and end <= window_end


def _meeting_fits(
    meeting: Meeting, *, student_tz: str, window_start_hour: int, window_end_hour: int
) -> bool:
    if meeting.start_local is None or meeting.end_local is None:
        raise ValueError("meeting has no start/end time")
    dates = [meeting.start_date or date.today()]
    if meeting.end_date is not None and meeting.end_date != dates[0]:
        dates.append(meeting.end_date)
    return all(
        _fits_on_date(
            meeting.start_local,
            meeting.end_local,
            on_date,
            meeting.timezone,
            student_tz=student_tz,
            window_start_hour=window_start_hour,
            window_end_hour=window_end_hour,
        )
        for on_date in dates
    )


def classify_fit(
    section: ParsedSection,
    *,
    student_tz: str,
    window_start_hour: int = 8,
    window_end_hour: int = 23,
) -> str:
    if not section.meetings:
        return FIT_ASYNC if section.modality == "async_online" else FIT_UNKNOWN
    timed = [m for m in section.meetings if m.is_timed]
    if not timed:
        all_online = all(m.is_online for m in section.meetings)
        return FIT_ASYNC if (section.modality == "async_online" or all_online) else FIT_UNKNOWN
    fits_all = all(
        _meeting_fits(
            m,
            student_tz=student_tz,
            window_start_hour=window_start_hour,
            window_end_hour=window_end_hour,
        )
        for m in timed
    )
    return FIT_FITS if fits_all else FIT_CONFLICTS
