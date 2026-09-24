from __future__ import annotations

from datetime import date, time

from src.schedule.colleague_sections import parse_meetings, parse_section

_BODY = {
    "Synonym": "130980", "Number": "201", "CourseName": "MATH-020",
    "Title": "College Algebra - Liberal Arts", "SectionTitleDisplay": "College Algebra - Liberal Arts",
    "Location": "EVC", "LocationDisplay": "Evergreen Valley College",
    "AvailabilityStatusDisplay": "Waitlisted", "Available": 13, "Capacity": 42, "Enrolled": 29,
    "InstructionalMethodsDisplay": ["Lecture"], "FacultyDisplay": ["Sylvia R. Anderson"],
    "FormattedMeetingTimes": [{
        "DaysOfWeekDisplay": "M/W", "StartTime": "10:45:00", "EndTime": "12:05:00",
        "Days": [1, 3], "IsOnline": False, "BuildingDisplay": "MS3 Building", "RoomDisplay": "MS217",
        "StartDate": "2026-08-24T00:00:00-07:00", "EndDate": "2026-12-10T00:00:00-08:00",
        "InstructionalMethodDisplay": "Lecture"}],
    "Meetings": [{"InstructionalMethodCode": "02", "Days": [1, 3], "Room": "2MS3*MS217", "IsOnline": False}],
}

_BODY_ONLINE = {
    **_BODY, "Synonym": "130999", "AvailabilityStatusDisplay": "Open", "Available": 20, "Enrolled": 22,
    "InstructionalMethodsDisplay": ["Online"],
    "FormattedMeetingTimes": [{"Days": [], "IsOnline": True, "StartTime": None, "EndTime": None,
        "BuildingDisplay": "", "RoomDisplay": "", "StartDate": "2026-08-24T00:00:00-07:00",
        "EndDate": "2026-12-10T00:00:00-08:00", "InstructionalMethodDisplay": "Online"}],
    "Meetings": [],
}


def test_parse_meetings_from_formatted_times():
    (m,) = parse_meetings(_BODY)
    assert m.days == ("M", "W")
    assert m.start_local == time(10, 45)
    assert m.end_local == time(12, 5)
    assert m.location == "MS3 Building MS217"
    assert m.is_online is False
    assert m.start_date == date(2026, 8, 24)
    assert m.end_date == date(2026, 12, 10)


def test_parse_meetings_falls_back_to_raw_meetings():
    body = {**_BODY, "FormattedMeetingTimes": None}
    (m,) = parse_meetings(body)
    assert m.days == ("M", "W")
    assert m.location == "2MS3*MS217"
    assert m.start_local is None


def test_parse_meetings_empty():
    assert parse_meetings({**_BODY, "FormattedMeetingTimes": [], "Meetings": []}) == ()


def test_parse_section_in_person_waitlisted():
    s = parse_section(_BODY, wrapper=None)
    assert s is not None
    assert s.section_id == "130980"
    assert s.status == "waitlist"
    assert s.modality == "in_person"
    assert s.title == "College Algebra - Liberal Arts"
    assert s.instructor == "Sylvia R. Anderson"
    assert s.seats_total == 42
    assert s.seats_used == 29
    assert s.course_code_as_listed == "MATH-020"
    assert len(s.meetings) == 1


def test_parse_section_online_async():
    s = parse_section(_BODY_ONLINE, wrapper=None)
    assert s is not None
    assert s.modality == "async_online"
    assert s.status == "open"


def test_parse_section_seats_used_derived_when_enrolled_missing():
    body = {k: v for k, v in _BODY.items() if k != "Enrolled"}
    s = parse_section(body, wrapper=None)
    assert s is not None
    assert s.seats_used == 29  # Capacity 42 - Available 13


def test_parse_section_instructor_from_wrapper_wins():
    s = parse_section(_BODY, wrapper={"FacultyDisplay": ["Wrapped Name"]})
    assert s is not None
    assert s.instructor == "Wrapped Name"


def test_parse_section_without_id_returns_none():
    body = {k: v for k, v in _BODY.items() if k not in ("Synonym", "Number", "Id")}
    assert parse_section(body, wrapper=None) is None
