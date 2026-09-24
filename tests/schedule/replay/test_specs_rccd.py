"""Riverside district specs (78, 148, 149) against a recorded OData sample."""
from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest

from src.schedule.catalog import get_college_source
from src.schedule.generic_replay import GenericReplayProvider
from src.schedule.replay.executor import HostThrottle, ReplayExecutor
from src.schedule.term import TermNotListedError, parse_term_label

from .fakes import FakeSession

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "replay"
_HOST = "https://apps-studentrcc.msappproxy.net/schedule/_api/web/lists/getByTitle('ScheduleData_"
_SAMPLE = (_FIXTURES / "rccd_riv_sample.json").read_text()


def _term_seen(code: str) -> str:
    return '{"value": [{"Term": "%s"}]}' % code


def _routes(search_body: str, term_code: str = "26FAL") -> dict[str, object]:
    """The term check and the search share a URL prefix: term-check body first, then search."""
    return {_HOST: [_term_seen(term_code), search_body]}


def _provider(session: FakeSession) -> GenericReplayProvider:
    return GenericReplayProvider(
        executor=ReplayExecutor(session, throttle=HostThrottle(0.0), sleeper=lambda s: None))


@pytest.mark.parametrize("cc_id,list_code", [(78, "RIV"), (148, "NOR"), (149, "MOV")])
def test_request_shape_and_term_codes(cc_id: int, list_code: str):
    session = FakeSession(_routes(_SAMPLE))
    source = get_college_source(cc_id)
    _provider(session).search_course(source=source, term=parse_term_label("Fall 2026"), course_code="MAT 1B")
    check, call = session.calls
    assert check["url"] == f"{_HOST}{list_code}')/items"
    assert check["params"] == {"$filter": "Term eq '26FAL'", "$select": "Term", "$top": "1"}
    assert check["headers"]["Accept"] == "application/json;odata=nometadata"
    assert call["url"] == f"{_HOST}{list_code}')/items"
    assert call["params"]["$filter"] == "Term eq '26FAL' and Primary_x0020_Subject eq 'MAT-1B'"
    assert call["params"]["$top"] == "500"
    assert call["headers"]["Accept"] == "application/json;odata=nometadata"


@pytest.mark.parametrize("label,code", [("Spring 2027", "27SPR"), ("Summer 2026", "26SUM")])
def test_other_seasons(label: str, code: str):
    session = FakeSession(_routes('{"value": []}', code))
    _provider(session).search_course(source=get_college_source(78), term=parse_term_label(label), course_code="MATH C2220")
    assert session.calls[0]["params"]["$filter"] == f"Term eq '{code}'"
    assert session.calls[1]["params"]["$filter"] == f"Term eq '{code}' and Primary_x0020_Subject eq 'MATH-C2220'"


def test_sections_meetings_seats_and_modality():
    session = FakeSession(_routes(_SAMPLE))
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
    session = FakeSession(_routes('{"value": []}'))
    out = _provider(session).search_course(
        source=get_college_source(78), term=parse_term_label("Fall 2026"), course_code="MAT 1B")
    assert out.offered is False and out.sections == []


@pytest.mark.parametrize("cc_id", [78, 148, 149])
def test_unpublished_term_is_term_not_listed(cc_id: int):
    session = FakeSession({_HOST: '{"value": []}'})
    with pytest.raises(TermNotListedError):
        _provider(session).search_course(
            source=get_college_source(cc_id), term=parse_term_label("Fall 2027"), course_code="MATH C2220")
    assert len(session.calls) == 1


def test_term_check_is_cached_per_provider():
    session = FakeSession({_HOST: [_term_seen("26FAL"), _SAMPLE, '{"value": []}']})
    provider = _provider(session)
    fall = parse_term_label("Fall 2026")
    provider.search_course(source=get_college_source(78), term=fall, course_code="MATH C2220")
    provider.search_course(source=get_college_source(78), term=fall, course_code="MAT 1B")
    assert [c["params"]["$filter"].startswith("Term eq '26FAL' and") for c in session.calls] == [False, True, True]


_LISTING_SAMPLE = (_FIXTURES / "rccd_riv_listing_math.json").read_text()


@pytest.mark.parametrize("cc_id,list_code", [(78, "RIV"), (148, "NOR"), (149, "MOV")])
def test_listing_request_shape(cc_id: int, list_code: str):
    session = FakeSession(_routes(_LISTING_SAMPLE))
    courses = _provider(session).list_subject(
        source=get_college_source(cc_id), term=parse_term_label("Fall 2026"), subject="MATH")
    check, call = session.calls
    assert check["params"] == {"$filter": "Term eq '26FAL'", "$select": "Term", "$top": "1"}
    assert call["url"] == f"{_HOST}{list_code}')/items"
    assert call["params"] == {
        "$filter": "Term eq '26FAL' and startswith(Primary_x0020_Subject,'MATH-')",
        "$select": "Primary_x0020_Subject,Title,Description",
        "$top": "1000",
    }
    assert [(c.code, c.title) for c in courses] == [
        ("MATH-1C", "Calculus III"), ("MATH-2", "Differential Equations"),
        ("MATH-C2220", "Calculus II: Early Transcendentals"),
    ]
    assert courses[2].description.startswith("A second course in differential and integral calculus")


def test_listing_unpublished_term_is_term_not_listed():
    session = FakeSession({_HOST: ['{"value": []}']})
    with pytest.raises(TermNotListedError):
        _provider(session).list_subject(
            source=get_college_source(78), term=parse_term_label("Fall 2027"), subject="MATH")
