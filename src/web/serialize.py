"""Convert schedule dataclasses to JSON-ready dicts for the API."""
from __future__ import annotations

from datetime import date, time
from typing import Any

from src.schedule.fit import classify_fit
from src.schedule.models import Meeting, ParsedSection


def _time_str(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


def _date_str(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def meeting_to_dict(meeting: Meeting) -> dict[str, Any]:
    return {
        "days": list(meeting.days),
        "start_local": _time_str(meeting.start_local),
        "end_local": _time_str(meeting.end_local),
        "timezone": meeting.timezone,
        "location": meeting.location,
        "is_online": meeting.is_online,
        "start_date": _date_str(meeting.start_date),
        "end_date": _date_str(meeting.end_date),
    }


def section_to_dict(section: ParsedSection, *, student_utc_offset_minutes: int | None) -> dict[str, Any]:
    fit = (
        classify_fit(section, student_utc_offset_minutes=student_utc_offset_minutes)
        if student_utc_offset_minutes is not None
        else None
    )
    return {
        "section_id": section.section_id,
        "status": section.status,
        "modality": section.modality,
        "title": section.title,
        "instructor": section.instructor,
        "meetings": [meeting_to_dict(m) for m in section.meetings],
        "seats_total": section.seats_total,
        "seats_used": section.seats_used,
        "course_code_as_listed": section.course_code_as_listed,
        "fit": fit,
    }
