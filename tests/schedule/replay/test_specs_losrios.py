"""Los Rios specs (27 ARC, 142 CRC, 145 FLC, 126 SCC) against recorded HTML samples."""
from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest

from src.schedule.catalog import get_college_source
from src.schedule.errors import PortalChanged
from src.schedule.generic_replay import GenericReplayProvider
from src.schedule.replay.executor import HostThrottle, ReplayExecutor
from src.schedule.term import TermNotListedError, parse_term_label

from .fakes import FakeSession

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "replay"
_TERMS_URL = "https://losrios.edu/academics/search-class-schedules"
_SEARCH_URL = "https://hub.losrios.edu/classSearch/getCourses.php"


def _session(cards: str | None = None) -> FakeSession:
    return FakeSession({
        _TERMS_URL: (_FIXTURES / "losrios_terms_page.html").read_text(),
        _SEARCH_URL: cards if cards is not None else (_FIXTURES / "losrios_arc_math_cards.html").read_text(),
    })


def _provider(session: FakeSession) -> GenericReplayProvider:
    return GenericReplayProvider(
        executor=ReplayExecutor(session, throttle=HostThrottle(0.0), sleeper=lambda s: None))


def _search(cc_id: int, course_code: str, label: str = "Fall 2026", session: FakeSession | None = None):
    session = session or _session()
    out = _provider(session).search_course(
        source=get_college_source(cc_id), term=parse_term_label(label), course_code=course_code)
    return out, session


@pytest.mark.parametrize("cc_id,flag,href", [
    (27, "arcFilter", "arc"), (142, "crcFilter", "crc"), (145, "flcFilter", "flc"), (126, "sccFilter", "scc"),
])
def test_request_shape_per_college(cc_id: int, flag: str, href: str):
    _, session = _search(cc_id, "MATH 400")
    assert session.calls[0]["url"] == _TERMS_URL
    params = session.calls[1]["params"]
    assert session.calls[1]["url"] == _SEARCH_URL
    assert params[flag] == "true" and params["href"] == href
    assert {k for k, v in params.items() if k.endswith("Filter") and v == "true"} == {flag}
    assert params["subjectFilters"] == "MATH" and params["searchBar"] == "MATH 400"
    assert params["strm"] == "1269" and params["offset"] == "0" and params["first"] == "1"


def test_arc_math_400_sections():
    out, _ = _search(27, "MATH 400")
    assert out.offered is True
    assert [s.section_id for s in out.sections] == ["10414", "10413"]
    first = out.sections[0]
    assert first.title == "Calculus I" and first.course_code_as_listed == "MATH 400"
    assert first.instructor == "Karsten Stemmann" and first.status == "closed"
    assert first.modality == "in_person" and first.seats_total is None
    meeting = first.meetings[0]
    assert meeting.days == ("M", "W") and meeting.start_local == time(15, 0) and meeting.end_local == time(17, 20)
    assert meeting.location == "Main Campus, STEM , 310" and meeting.is_online is False
    assert out.sections[1].meetings[0].start_local == time(8, 0)


def test_arc_math_300_online_section_filtered_by_code():
    out, _ = _search(27, "MATH 300")
    assert [s.section_id for s in out.sections] == ["12286"]
    section = out.sections[0]
    assert section.modality == "async_online" and section.meetings == ()
    assert section.instructor == "Trisha R. Butler"


def test_other_college_cards_are_filtered_out():
    out, _ = _search(142, "MATH 400")  # cards say "American River College"
    assert out.offered is False and out.sections == []


def test_zero_results_page_is_not_offered():
    page = "<div class='filter-results'><span id='totalResults' style='display:inline-block;'>0</span></div><ul class='class-cards'></ul>"
    out, _ = _search(27, "MATH 9999", session=_session(cards=page))
    assert out.offered is False


def test_page_without_marker_is_portal_changed():
    with pytest.raises(PortalChanged, match="totalResults"):
        _search(27, "MATH 400", session=_session(cards="<html><body>Down for maintenance</body></html>"))


def test_pagination_requests_second_page_when_total_exceeds_20():
    cards = (_FIXTURES / "losrios_arc_math_cards.html").read_text().replace(
        "display:inline-block;'>3<", "display:inline-block;'>28<")
    out, session = _search(27, "MATH 400", session=_session(cards=cards))
    search_calls = [c for c in session.calls if c["url"] == _SEARCH_URL]
    assert [c["params"]["offset"] for c in search_calls] == ["0", "1"]
    assert len(out.sections) == 4  # both fake pages carry the same two MATH 400 cards


def test_terms_page_is_cached_across_courses():
    session = _session()
    provider = _provider(session)
    for code in ("MATH 400", "MATH 401"):
        provider.search_course(source=get_college_source(27), term=parse_term_label("Fall 2026"), course_code=code)
    assert [c["url"] for c in session.calls].count(_TERMS_URL) == 1


def test_unlisted_term_is_term_not_listed():
    with pytest.raises(TermNotListedError, match="Summer 2027"):
        _search(27, "MATH 400", label="Summer 2027")
