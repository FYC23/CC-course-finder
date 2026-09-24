"""Riverside district specs (78, 148, 149) against a recorded OData sample."""
from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest

from src.schedule.catalog import get_college_source
from src.schedule.generic_replay import GenericReplayProvider
from src.schedule.replay.executor import HostThrottle, ReplayExecutor
from src.schedule.term import parse_term_label

from .fakes import FakeSession

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "replay"
_HOST = "https://apps-studentrcc.msappproxy.net/schedule/_api/web/lists/getByTitle('ScheduleData_"


def _provider(session: FakeSession) -> GenericReplayProvider:
    return GenericReplayProvider(
        executor=ReplayExecutor(session, throttle=HostThrottle(0.0), sleeper=lambda s: None))


@pytest.mark.parametrize("cc_id,list_code", [(78, "RIV"), (148, "NOR"), (149, "MOV")])
def test_request_shape_and_term_codes(cc_id: int, list_code: str):
    session = FakeSession({_HOST: (_FIXTURES / "rccd_riv_sample.json").read_text()})
    source = get_college_source(cc_id)
    _provider(session).search_course(source=source, term=parse_term_label("Fall 2026"), course_code="MAT 1B")
    call = session.calls[0]
    assert call["url"] == f"{_HOST}{list_code}')/items"
    assert call["params"]["$filter"] == "Term eq '26FAL' and Primary_x0020_Subject eq 'MAT-1B'"
    assert call["params"]["$top"] == "500"
    assert call["headers"]["Accept"] == "application/json;odata=nometadata"


@pytest.mark.parametrize("label,code", [("Spring 2027", "27SPR"), ("Summer 2026", "26SUM")])
def test_other_seasons(label: str, code: str):
    session = FakeSession({_HOST: '{"value": []}'})
    _provider(session).search_course(source=get_college_source(78), term=parse_term_label(label), course_code="MATH C2220")
    assert session.calls[0]["params"]["$filter"] == f"Term eq '{code}' and Primary_x0020_Subject eq 'MATH-C2220'"


def test_sections_meetings_seats_and_modality():
    session = FakeSession({_HOST: (_FIXTURES / "rccd_riv_sample.json").read_text()})
    out = _provider(session).search_course(
        source=get_college_source(78), term=parse_term_label("Fall 2026"), course_code="MATH C2220")
    assert out.offered is True and out.lookup_error is None
    lecture, online = out.sections
    assert lecture.section_id == "49060" and lecture.title == "Calculus II: Early Transcendentals"
    assert lecture.instructor == "E Enright" and lecture.course_code_as_listed == "MATH-C2220"
    assert lecture.seats_total == 42 and lecture.seats_used == 36 and lecture.status == "open"
    assert lecture.modality == "in_person"
    assert len(lecture.meetings) == 5
    assert lecture.meetings[0].days == ("M",) and lecture.meetings[0].start_local == time(8, 0)
    assert lecture.meetings[1].days == ("W", "F") and lecture.meetings[1].end_local == time(8, 55)
    assert lecture.meetings[0].location == "MTSC 106" and lecture.meetings[0].is_online is False
    assert lecture.meetings[0].start_date == date(2026, 8, 24) and lecture.meetings[0].end_date == date(2026, 12, 18)
    assert online.section_id == "49087" and online.modality == "async_online"
    assert len(online.meetings) == 1 and online.meetings[0].is_online is True
    assert online.meetings[0].days == () and online.meetings[0].start_local is None
    assert online.status == "open"


def test_empty_value_is_not_offered():
    session = FakeSession({_HOST: '{"value": []}'})
    out = _provider(session).search_course(
        source=get_college_source(78), term=parse_term_label("Fall 2026"), course_code="MAT 1B")
    assert out.offered is False and out.sections == []
