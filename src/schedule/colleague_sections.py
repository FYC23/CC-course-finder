"""Parse Colleague Self-Service section JSON into ParsedSection and Meeting."""
from __future__ import annotations

from .models import Meeting, ParsedSection
from .normalize import (
    days_from_indices,
    int_or_none,
    normalize_modality,
    normalize_status,
    parse_date,
    parse_hhmm,
)


def _first_str(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
    return None


def _meeting_from_formatted(entry: dict) -> Meeting:
    building = str(entry.get("BuildingDisplay") or "").strip()
    room = str(entry.get("RoomDisplay") or "").strip()
    return Meeting(
        days=days_from_indices(entry.get("Days") or []),
        start_local=parse_hhmm(entry.get("StartTime")),
        end_local=parse_hhmm(entry.get("EndTime")),
        location=" ".join(part for part in (building, room) if part),
        is_online=bool(entry.get("IsOnline")),
        start_date=parse_date(entry.get("StartDate")),
        end_date=parse_date(entry.get("EndDate")),
    )


def _meeting_from_raw(entry: dict) -> Meeting:
    return Meeting(
        days=days_from_indices(entry.get("Days") or []),
        location=str(entry.get("Room") or "").strip(),
        is_online=bool(entry.get("IsOnline")),
        start_date=parse_date(entry.get("StartDate")),
        end_date=parse_date(entry.get("EndDate")),
    )


def parse_meetings(body: dict) -> tuple[Meeting, ...]:
    formatted = body.get("FormattedMeetingTimes")
    if isinstance(formatted, list) and formatted:
        return tuple(_meeting_from_formatted(e) for e in formatted if isinstance(e, dict))
    raw = body.get("Meetings")
    if isinstance(raw, list) and raw:
        return tuple(_meeting_from_raw(e) for e in raw if isinstance(e, dict))
    return ()


def _method_tokens(body: dict, meetings: tuple[Meeting, ...]) -> list[str]:
    tokens: list[str] = []
    methods = body.get("InstructionalMethodsDisplay")
    if isinstance(methods, list):
        tokens.extend(str(m) for m in methods)
    elif isinstance(methods, str):
        tokens.append(methods)
    for entry in body.get("FormattedMeetingTimes") or []:
        if isinstance(entry, dict) and entry.get("InstructionalMethodDisplay"):
            tokens.append(str(entry["InstructionalMethodDisplay"]))
    return tokens


def _instructor(*, wrapper: dict | None, body: dict) -> str:
    for source in (wrapper or {}, body):
        faculty = source.get("FacultyDisplay")
        if isinstance(faculty, list):
            names = [str(name).strip() for name in faculty if str(name).strip()]
            if names:
                return ", ".join(names)
        if isinstance(faculty, str) and faculty.strip():
            return faculty.strip()
    return ""


def _seats_used(body: dict) -> int | None:
    enrolled = int_or_none(body.get("Enrolled"))
    if enrolled is not None:
        return enrolled
    capacity = int_or_none(body.get("Capacity"))
    available = int_or_none(body.get("Available"))
    if capacity is None or available is None:
        return None
    return capacity - available


def parse_section(body: dict, wrapper: dict | None) -> ParsedSection | None:
    section_id = _first_str(body.get("Synonym"), body.get("Number"), body.get("Id"))
    if section_id is None:
        return None
    meetings = parse_meetings(body)
    title = _first_str(body.get("Title"), body.get("SectionTitleDisplay"), body.get("CourseName")) or ""
    return ParsedSection(
        section_id=section_id,
        status=normalize_status(
            _first_str(body.get("AvailabilityStatusDisplay"), body.get("AvailabilityStatus"))
        ),
        modality=normalize_modality(raw_tokens=_method_tokens(body, meetings), meetings=meetings),
        title=title,
        instructor=_instructor(wrapper=wrapper, body=body),
        meetings=meetings,
        seats_total=int_or_none(body.get("Capacity")),
        seats_used=_seats_used(body),
        course_code_as_listed=_first_str(body.get("CourseName")) or "",
    )
