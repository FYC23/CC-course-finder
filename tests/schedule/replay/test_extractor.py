from __future__ import annotations

import json
from datetime import date, time

import pytest

from src.schedule.errors import PortalChanged
from src.schedule.replay.extractor import extract_sections
from src.schedule.replay.spec import (
    Extract, FilterRule, MeetingRule, ValueRule, value_rule,
)

_VALUES = {"subject": "MATH", "number": "400"}


def _json_extract(**overrides) -> Extract:
    base = dict(
        kind="json", rows="$.rows[*]",
        fields={"section_id": ValueRule(path="$.crn"), "title": ValueRule(path="$.title"),
                "instructor": ValueRule(path="$.who"), "seats_total": ValueRule(path="$.max"),
                "seats_used": ValueRule(path="$.used"),
                "course_code_as_listed": ValueRule(join=(ValueRule(path="$.subj"), ValueRule(path="$.num")))},
        status_from_seats=True,
        modality_tokens=(ValueRule(path="$.method"),),
        meetings=(MeetingRule(
            day_flags=tuple(ValueRule(path=f"$.{d}") for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")),
            start=ValueRule(path="$.begin"), end=ValueRule(path="$.end"),
            location=ValueRule(join=(ValueRule(path="$.bldg"), ValueRule(path="$.room"))),
            start_date=ValueRule(path="$.from"), end_date=ValueRule(path="$.to"),
        ),),
    )
    return Extract(**{**base, **overrides})


_ROW_IN_PERSON = {
    "crn": "49060", "title": "Calculus II", "who": "E Enright", "max": 42.0, "used": 36.0,
    "subj": "MATH", "num": "C2220", "method": "LEC",
    "mon": True, "tue": False, "wed": True, "thu": False, "fri": False, "sat": False, "sun": False,
    "begin": "08:00AM", "end": "09:00AM", "bldg": "MTSC", "room": "106",
    "from": "08/24/26", "to": "12/18/26",
}
_ROW_ONLINE = {
    "crn": "49087", "title": "Business Calc", "who": None, "max": 45.0, "used": 45.0,
    "subj": "MATH", "num": "5", "method": "OL",
    "mon": False, "tue": False, "wed": False, "thu": False, "fri": False, "sat": False, "sun": False,
    "begin": None, "end": None, "bldg": "ON", "room": "LINE", "from": "08/24/26", "to": "12/18/26",
}


def test_json_rows_fields_meetings_status_modality():
    body = json.dumps({"rows": [_ROW_IN_PERSON, _ROW_ONLINE]})
    sections = extract_sections([body], _json_extract(), _VALUES)
    assert [s.section_id for s in sections] == ["49060", "49087"]
    first, second = sections
    assert first.title == "Calculus II" and first.instructor == "E Enright"
    assert first.seats_total == 42 and first.seats_used == 36 and first.status == "open"
    assert first.course_code_as_listed == "MATH C2220"
    assert first.modality == "in_person"
    assert first.meetings[0].days == ("M", "W")
    assert first.meetings[0].start_local == time(8, 0) and first.meetings[0].end_local == time(9, 0)
    assert first.meetings[0].location == "MTSC 106" and first.meetings[0].is_online is False
    assert first.meetings[0].start_date == date(2026, 8, 24) and first.meetings[0].end_date == date(2026, 12, 18)
    assert second.instructor == "" and second.status == "closed"
    assert second.modality == "async_online"
    assert second.meetings[0].is_online is True and second.meetings[0].days == ()


def test_empty_meeting_slots_are_skipped():
    row = {**_ROW_IN_PERSON, "mon": False, "wed": False, "begin": None, "end": None, "bldg": None, "room": None}
    sections = extract_sections([json.dumps({"rows": [row]})], _json_extract(), _VALUES)
    assert sections[0].meetings == ()
    assert sections[0].modality == "in_person"  # from the LEC token


def test_each_iterates_nested_meetings():
    extract = _json_extract(meetings=(MeetingRule(
        each="$.meet[*]",
        day_flags=tuple(ValueRule(path=f"$.{d}") for d in ("monDay", "tueDay", "wedDay", "thuDay", "friDay", "satDay", "sunDay")),
        start=ValueRule(path="$.beginTime"), end=ValueRule(path="$.endTime"),
        location=ValueRule(join=(ValueRule(path="$.bldgCode"), ValueRule(path="$.roomCode"))),
    ),), modality_tokens=(ValueRule(path="$.meet[*].schdDesc"),))
    row = {**_ROW_IN_PERSON, "meet": [
        {"beginTime": "1615", "endTime": "1705", "tueDay": "T", "bldgCode": "SEM", "roomCode": "203", "schdDesc": "Lecture"},
        {"bldgCode": "ONLINE", "schdDesc": "Hybrid"},
    ]}
    section = extract_sections([json.dumps({"rows": [row]})], extract, _VALUES)[0]
    assert len(section.meetings) == 2
    assert section.meetings[0].days == ("T",) and section.meetings[0].start_local == time(16, 15)
    assert section.meetings[1].is_online is True and section.meetings[1].start_local is None
    assert section.modality == "hybrid"


def test_filters_compare_normalized_and_render_placeholders():
    extract = _json_extract(filters=(
        FilterRule(value=ValueRule(path="$.camp"), equals="1"),
        FilterRule(value=ValueRule(path="$.num"), any_of=("{number}", "{number}C")),
    ))
    rows = [
        {**_ROW_IN_PERSON, "crn": "a", "camp": "1", "num": "400"},
        {**_ROW_IN_PERSON, "crn": "b", "camp": "1", "num": "400 C"},
        {**_ROW_IN_PERSON, "crn": "c", "camp": "2", "num": "400"},
        {**_ROW_IN_PERSON, "crn": "d", "camp": "1", "num": "401"},
    ]
    sections = extract_sections([json.dumps({"rows": rows})], extract, _VALUES)
    assert [s.section_id for s in sections] == ["a", "b"]


def test_status_rule_beats_seats():
    extract = _json_extract(status=ValueRule(path="$.st"), status_from_seats=False)
    row = {**_ROW_IN_PERSON, "st": "Waitlisted"}
    assert extract_sections([json.dumps({"rows": [row]})], extract, _VALUES)[0].status == "waitlist"


def test_no_status_source_is_unknown():
    extract = _json_extract(status=None, status_from_seats=False)
    assert extract_sections([json.dumps({"rows": [_ROW_IN_PERSON]})], extract, _VALUES)[0].status == "unknown"


def test_modality_map_wins_over_normalization():
    extract = _json_extract(modality_map={"partially online": "hybrid"})
    row = {**_ROW_IN_PERSON, "method": "Partially Online"}
    assert extract_sections([json.dumps({"rows": [row]})], extract, _VALUES)[0].modality == "hybrid"


def test_seats_available_and_wait_capacity_feed_status():
    extract = _json_extract(fields={
        "section_id": ValueRule(path="$.crn"), "seats_available": ValueRule(path="$.avail"),
        "wait_capacity": ValueRule(path="$.wait")})
    body = json.dumps({"rows": [{"crn": "1", "avail": 0, "wait": 20}, {"crn": "2", "avail": 0, "wait": 0}]})
    assert [s.status for s in extract_sections([body], extract, _VALUES)] == ["waitlist", "closed"]


def test_multiple_bodies_are_concatenated():
    bodies = [json.dumps({"rows": [_ROW_IN_PERSON]}), json.dumps({"rows": [_ROW_ONLINE]})]
    assert len(extract_sections(bodies, _json_extract(), _VALUES)) == 2


def test_rows_container_missing_is_portal_changed():
    with pytest.raises(PortalChanged, match="rows"):
        extract_sections([json.dumps({"other": []})], _json_extract(), _VALUES)


def test_rows_container_null_is_no_sections():
    assert extract_sections([json.dumps({"rows": None})], _json_extract(), _VALUES) == ()


def test_rows_container_not_a_list_is_portal_changed():
    with pytest.raises(PortalChanged, match="list"):
        extract_sections([json.dumps({"rows": {"a": 1}})], _json_extract(), _VALUES)


def test_body_not_json_is_portal_changed():
    with pytest.raises(PortalChanged, match="JSON"):
        extract_sections(["<html>"], _json_extract(), _VALUES)


# --- html ------------------------------------------------------------------------------

_HTML = """
<div class='filter-results'><span id='totalResults'>2</span></div>
<ul class='class-cards'>
<li><article class="class-card">
  <div class="title"><span class="class-card-subj-num">
      MATH 400</span> Calculus I</div>
  <span class="college">American River College</span>
  <ul>
    <li class="section"><span class="label">Class</span> LEC&nbsp;10414</li>
    <li><span class="label">Mode</span> In Person</li>
    <li><span class='label'>Day/Time</span>Mon/Wed, 3:00 pm to 5:20 pm</li>
    <li><span class='label'>Building<!-- 1 --></span>Main Campus,
STEM
, 310</li>
    <li><span class='label'>Instructor</span><a href="/x">Karsten Stemmann</a></li>
    <li class="status"><span class='highlight highlight--closed'></span>Closed</li>
  </ul>
</article></li>
<li><article class="class-card">
  <div class="title"><span class="class-card-subj-num">MATH 300</span> Intro Ideas</div>
  <span class="college">American River College</span>
  <ul>
    <li class="section"><span class="label">Class</span> LEC&nbsp;12286</li>
    <li><span class="label">Mode</span> Fully Online</li>
    <li><span class='label'>Day/Time</span>Asynchronous – no scheduled meeting times</li>
    <li><span class='label'>Instructor</span><a href="/y">Trisha R. Butler</a></li>
    <li class="status"><span class='highlight'></span>Open</li>
  </ul>
</article></li>
</ul>
"""


def _html_extract(**overrides) -> Extract:
    kind = "html"
    base = dict(
        kind=kind, rows="article.class-card", marker="div.filter-results",
        fields={
            "section_id": value_rule({"css": "li.section", "regex": r"(\d+)\s*$"}, kind),
            "title": value_rule({"css": "div.title", "regex": r"^[A-Z]+ [A-Z0-9]+\s+(.+)$"}, kind),
            "instructor": value_rule({"css": "li:has(> span.label:-soup-contains('Instructor'))",
                                      "regex": r"^Instructor\s*(.*)$"}, kind),
            "course_code_as_listed": value_rule("span.class-card-subj-num", kind),
        },
        status=value_rule("li.status", kind),
        modality_tokens=(value_rule({"css": "li:has(> span.label:-soup-contains('Mode'))",
                                     "regex": r"^Mode\s*(.*)$"}, kind),),
        modality_map={"partially online": "hybrid"},
        meetings=(MeetingRule(
            time_text=value_rule("li:has(> span.label:-soup-contains('Day/Time'))", kind),
            time_pattern=r"^Day/Time\s*(?P<days>[A-Za-z/]+), (?P<start>\d{1,2}:\d{2} [ap]m) to (?P<end>\d{1,2}:\d{2} [ap]m)",
            location=value_rule({"css": "li:has(> span.label:-soup-contains('Building'))",
                                 "regex": r"^Building\s*(.*)$"}, kind),
        ),),
    )
    return Extract(**{**base, **overrides})


def test_html_rows_fields_and_meeting_text():
    sections = extract_sections([_HTML], _html_extract(), _VALUES)
    assert [s.section_id for s in sections] == ["10414", "12286"]
    first, second = sections
    assert first.title == "Calculus I" and first.instructor == "Karsten Stemmann"
    assert first.course_code_as_listed == "MATH 400" and first.status == "closed"
    assert first.modality == "in_person"
    meeting = first.meetings[0]
    assert meeting.days == ("M", "W")
    assert meeting.start_local == time(15, 0) and meeting.end_local == time(17, 20)
    assert meeting.location == "Main Campus, STEM , 310"
    assert second.status == "open" and second.modality == "async_online"
    assert second.meetings == ()


def test_html_filter_on_course_code():
    extract = _html_extract(filters=(FilterRule(
        value=value_rule("span.class-card-subj-num", "html"), equals="{subject} {number}"),))
    sections = extract_sections([_HTML], extract, _VALUES)
    assert [s.section_id for s in sections] == ["10414"]


def test_html_missing_marker_is_portal_changed():
    with pytest.raises(PortalChanged, match="marker"):
        extract_sections(["<html><body>Maintenance</body></html>"], _html_extract(), _VALUES)


def test_html_no_rows_with_marker_is_no_sections():
    page = "<div class='filter-results'><span id='totalResults'>0</span></div>"
    assert extract_sections([page], _html_extract(), _VALUES) == ()


def test_html_attr_rule():
    extract = _html_extract(fields={"section_id": value_rule({"css": "li a", "attr": "href"}, "html")})
    assert [s.section_id for s in extract_sections([_HTML], extract, _VALUES)] == ["/x", "/y"]


def test_html_field_attr_is_space_joined_for_multivalued_class():
    html = "<ul><li><a class='foo bar'>n</a></li></ul>"
    extract = Extract(
        kind="html", rows="li",
        fields={"section_id": value_rule({"css": "a", "attr": "class"}, "html")},
    )
    sections = extract_sections([html], extract, _VALUES)
    assert sections[0].section_id == "foo bar"
