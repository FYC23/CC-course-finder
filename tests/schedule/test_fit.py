from __future__ import annotations

from datetime import date, time

from src.schedule.fit import classify_fit, to_student_local
from src.schedule.models import Meeting, ParsedSection


def _section(modality="in_person", meetings=()) -> ParsedSection:
    return ParsedSection(section_id="1", status="open", modality=modality, title="T", instructor="",
                         meetings=tuple(meetings))


PDT = date(2026, 8, 24)   # UTC-7
PST = date(2026, 12, 1)   # UTC-8
CHINA = 480               # UTC+8


def test_to_student_local_pdt():
    # 07:30 PDT = 14:30 UTC = 22:30 China
    assert to_student_local(time(7, 30), PDT, "America/Los_Angeles", CHINA) == (time(22, 30), 0)


def test_to_student_local_pst_crosses_midnight():
    # 18:00 PST = 02:00 UTC next day = 10:00 China next day
    assert to_student_local(time(18, 0), PST, "America/Los_Angeles", CHINA) == (time(10, 0), 1)


def test_no_meetings_is_unknown():
    assert classify_fit(_section(), student_utc_offset_minutes=CHINA) == "unknown"


def test_no_meetings_async_online_is_async():
    """A section with async_online modality but no meeting rows at all (the portal never
    sent one) should still classify as async, not unknown."""
    s = _section(modality="async_online", meetings=[])
    assert classify_fit(s, student_utc_offset_minutes=CHINA) == "async"


def test_no_meetings_non_async_modality_is_unknown():
    s = _section(modality="hybrid", meetings=[])
    assert classify_fit(s, student_utc_offset_minutes=CHINA) == "unknown"


def test_untimed_online_is_async():
    s = _section(modality="async_online", meetings=[Meeting(is_online=True)])
    assert classify_fit(s, student_utc_offset_minutes=CHINA) == "async"


def test_untimed_in_person_is_unknown():
    s = _section(modality="in_person", meetings=[Meeting(location="TBA")])
    assert classify_fit(s, student_utc_offset_minutes=CHINA) == "unknown"


def test_morning_pacific_fits_china_evening():
    # 06:30-08:00 PDT = 21:30-23:00 China, inside the default 08..23 window
    m = Meeting(days=("M",), start_local=time(6, 30), end_local=time(8, 0), start_date=PDT)
    assert classify_fit(_section(meetings=[m]), student_utc_offset_minutes=CHINA) == "fits"


def test_meeting_ending_past_student_midnight_conflicts():
    # 07:30-09:00 PDT = 22:30-00:00 China; the end crosses midnight, so it conflicts
    m = Meeting(days=("M",), start_local=time(7, 30), end_local=time(9, 0), start_date=PDT)
    assert classify_fit(_section(meetings=[m]), student_utc_offset_minutes=CHINA) == "conflicts"


def test_afternoon_pacific_conflicts_china_night():
    m = Meeting(days=("M",), start_local=time(14, 0), end_local=time(15, 30), start_date=PDT)
    assert classify_fit(_section(meetings=[m]), student_utc_offset_minutes=CHINA) == "conflicts"


def test_custom_window():
    m = Meeting(days=("M",), start_local=time(14, 0), end_local=time(15, 30), start_date=PDT)
    # 14:00 PDT = 05:00 China; allow 5..23
    assert classify_fit(_section(meetings=[m]), student_utc_offset_minutes=CHINA,
                        window_start_hour=5, window_end_hour=23) == "fits"


def test_any_conflicting_meeting_conflicts():
    ok = Meeting(days=("M",), start_local=time(6, 30), end_local=time(8, 0), start_date=PDT)
    bad = Meeting(days=("W",), start_local=time(14, 0), end_local=time(15, 0), start_date=PDT)
    assert classify_fit(_section(meetings=[ok, bad]), student_utc_offset_minutes=CHINA) == "conflicts"


def test_pacific_student_fits_by_identity():
    m = Meeting(days=("M",), start_local=time(14, 0), end_local=time(15, 30), start_date=PDT)
    assert classify_fit(_section(meetings=[m]), student_utc_offset_minutes=-420) == "fits"


def test_dst_change_across_term_conflicts():
    # 16:00-17:30 campus-local, term spans PDT (start_date) through PST (end_date).
    # In PDT it's 07:00-08:30 China, before the window; in PST it's 08:00-09:30, which fits.
    # Since it must fit on both ends, the mismatch makes it "conflicts".
    m = Meeting(days=("M",), start_local=time(16, 0), end_local=time(17, 30),
                start_date=PDT, end_date=PST)
    assert classify_fit(_section(meetings=[m]), student_utc_offset_minutes=CHINA) == "conflicts"


def test_same_times_without_dst_crossing_fits():
    # Same campus-local times, but only evaluated on the PST date (no end_date/no DST switch).
    m = Meeting(days=("M",), start_local=time(16, 0), end_local=time(17, 30), start_date=PST)
    assert classify_fit(_section(meetings=[m]), student_utc_offset_minutes=CHINA) == "fits"


def test_no_start_date_uses_today_fallback_and_fits():
    m = Meeting(days=("M",), start_local=time(12, 0), end_local=time(13, 0))
    assert classify_fit(_section(meetings=[m]), student_utc_offset_minutes=-420) == "fits"
