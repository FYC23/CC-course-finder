from __future__ import annotations

from datetime import date, time

import pytest

from src.schedule.models import Meeting, ParsedSection
from src.schedule.normalize import (
    days_from_flags,
    days_from_indices,
    int_or_none,
    normalize_modality,
    normalize_status,
    parse_date,
    parse_hhmm,
)


# --- time parsing -----------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0730", time(7, 30)),
        ("1345", time(13, 45)),
        ("10:45:00", time(10, 45)),
        ("10:45", time(10, 45)),
        ("10:45 AM", time(10, 45)),
        ("02:20PM", time(14, 20)),
        ("12:05 PM", time(12, 5)),
        ("12:10AM", time(0, 10)),
        ("", None),
        (None, None),
        ("TBA", None),
    ],
)
def test_parse_hhmm(raw, expected):
    assert parse_hhmm(raw) == expected


# --- date parsing -----------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("08/24/2026", date(2026, 8, 24)),
        ("2026-08-24T00:00:00-07:00", date(2026, 8, 24)),
        ("2026-08-24", date(2026, 8, 24)),
        ("08/24/26", date(2026, 8, 24)),
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


# --- days -------------------------------------------------------------------

def test_days_from_flags_orders_monday_first():
    flags = {"monday": True, "wednesday": True, "sunday": True, "tuesday": False}
    assert days_from_flags(flags) == ("M", "W", "U")


def test_days_from_flags_ignores_unknown_keys():
    assert days_from_flags({"funday": True, "friday": True}) == ("F",)


def test_days_from_indices_colleague_convention():
    # Colleague: 0=Sunday ... 6=Saturday
    assert days_from_indices([1, 3]) == ("M", "W")
    assert days_from_indices([0, 6]) == ("S", "U")
    assert days_from_indices([]) == ()
    assert days_from_indices([9, -1]) == ()


# --- modality ---------------------------------------------------------------

def _meeting(**kw) -> Meeting:
    return Meeting(**kw)


def test_modality_hybrid_token_wins():
    assert normalize_modality(raw_tokens=["Hybrid"], meetings=()) == "hybrid"


def test_modality_online_with_no_times_is_async():
    m = _meeting(is_online=True)
    assert normalize_modality(raw_tokens=["Online"], meetings=(m,)) == "async_online"


def test_modality_online_with_times_is_sync():
    m = _meeting(is_online=True, days=("M",), start_local=time(9), end_local=time(10))
    assert normalize_modality(raw_tokens=["Online"], meetings=(m,)) == "sync_online"


def test_modality_online_token_alone_is_async():
    assert normalize_modality(raw_tokens=["OL"], meetings=()) == "async_online"


def test_modality_lecture_with_room_is_in_person():
    m = _meeting(days=("T",), start_local=time(9), end_local=time(10), location="MS3 217")
    assert normalize_modality(raw_tokens=["Lecture"], meetings=(m,)) == "in_person"


def test_modality_mixed_meetings_is_hybrid():
    online = _meeting(is_online=True)
    room = _meeting(days=("T",), start_local=time(9), end_local=time(10), location="QD 116")
    assert normalize_modality(raw_tokens=[], meetings=(online, room)) == "hybrid"


def test_modality_no_evidence_is_unknown():
    assert normalize_modality(raw_tokens=[], meetings=()) == "unknown"
    assert normalize_modality(raw_tokens=["02"], meetings=()) == "unknown"


# --- status -----------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Open", "open"),
        ("open seats", "open"),
        ("Closed", "closed"),
        ("Full", "closed"),
        ("Cancelled", "closed"),
        ("Waitlisted", "waitlist"),
        ("Waitlist", "waitlist"),
        ("", "unknown"),
        (None, "unknown"),
        ("Something else", "unknown"),
    ],
)
def test_normalize_status(raw, expected):
    assert normalize_status(raw) == expected


# --- ints -------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [(3, 3), (3.0, 3), ("42", 42), ("", None), (None, None), ("x", None), (-4, -4)])
def test_int_or_none(value, expected):
    assert int_or_none(value) == expected


# --- model defaults ---------------------------------------------------------

def test_parsed_section_defaults_are_backward_compatible():
    s = ParsedSection(section_id="1", status="open", modality="unknown", title="T", instructor="")
    assert s.meetings == ()
    assert s.seats_total is None
    assert s.seats_used is None
    assert s.course_code_as_listed == ""


def test_meeting_is_frozen():
    m = Meeting(days=("M",))
    with pytest.raises(Exception):
        m.days = ("T",)  # type: ignore[misc]
