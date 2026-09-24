from __future__ import annotations

from datetime import date, time

from src.schedule.models import Meeting, ParsedSection
from src.web.serialize import section_to_dict

_SECTION = ParsedSection(
    section_id="21216", status="open", modality="in_person", title="Calc", instructor="N",
    meetings=(Meeting(days=("M", "W"), start_local=time(7, 30), end_local=time(9, 35),
                      location="Bldg 61 2306", start_date=date(2026, 8, 24), end_date=date(2026, 12, 13)),),
    seats_total=40, seats_used=36, course_code_as_listed="MATH 180",
)


def test_section_to_dict_without_timezone():
    d = section_to_dict(_SECTION, student_tz=None)
    assert d["section_id"] == "21216"
    assert d["fit"] is None
    assert d["seats_total"] == 40
    assert d["course_code_as_listed"] == "MATH 180"
    m = d["meetings"][0]
    assert m["days"] == ["M", "W"]
    assert m["start_local"] == "07:30"
    assert m["end_local"] == "09:35"
    assert m["start_date"] == "2026-08-24"
    assert m["timezone"] == "America/Los_Angeles"


def test_section_to_dict_with_timezone_adds_fit():
    # 07:30-09:35 PDT is 22:30-00:35 in Shanghai (UTC+8), which crosses midnight
    d = section_to_dict(_SECTION, student_tz="Asia/Shanghai")
    assert d["fit"] == "conflicts"
    # 07:30-09:35 Pacific is 08:30-10:35 in Denver (MDT in Aug, MST in Dec), inside 08..23
    assert section_to_dict(_SECTION, student_tz="America/Denver")["fit"] == "fits"


def test_section_to_dict_untimed_meeting_has_null_times():
    s = ParsedSection(section_id="1", status="open", modality="async_online", title="T", instructor="",
                      meetings=(Meeting(is_online=True),))
    d = section_to_dict(s, student_tz="Asia/Shanghai")
    assert d["meetings"][0]["start_local"] is None
    assert d["fit"] == "async"
