"""NOCCCD specs (71 Cypress, 134 Fullerton) against recorded terms.json and sections.json samples."""
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
_TERMS_URL = "https://schedule.nocccd.edu/data/terms.json"
_FALL_SECTIONS_URL = "https://schedule.nocccd.edu/data/202610/sections.json"
_SPRING_SECTIONS_URL = "https://schedule.nocccd.edu/data/202620/sections.json"


def _session() -> FakeSession:
    return FakeSession({
        _TERMS_URL: (_FIXTURES / "nocccd_terms.json").read_text(),
        _FALL_SECTIONS_URL: (_FIXTURES / "nocccd_sections_sample.json").read_text(),
        _SPRING_SECTIONS_URL: "[]",
    })


def _provider(session: FakeSession) -> GenericReplayProvider:
    return GenericReplayProvider(
        executor=ReplayExecutor(session, throttle=HostThrottle(0.0), sleeper=lambda s: None))


def _search(cc_id: int, course_code: str, label: str = "Fall 2026", session: FakeSession | None = None):
    session = session or _session()
    out = _provider(session).search_course(
        source=get_college_source(cc_id), term=parse_term_label(label), course_code=course_code)
    return out, session


def test_cypress_exact_code_with_campus_suffix():
    out, session = _search(71, "MATH 150AC")
    assert [c["url"] for c in session.calls] == [_TERMS_URL, _FALL_SECTIONS_URL]
    assert out.offered is True and [s.section_id for s in out.sections] == ["10444"]
    section = out.sections[0]
    assert section.course_code_as_listed == "MATH 150AC" and section.title == ""
    assert section.instructor == "Shihabi, Azzam"
    assert section.seats_total == 35 and section.seats_used == 32 and section.status == "open"
    assert section.modality == "in_person"
    meeting = section.meetings[0]
    assert meeting.days == ("T", "R") and meeting.start_local == time(8, 15) and meeting.end_local == time(10, 20)
    assert meeting.location == "SEM 304" and meeting.is_online is False
    assert meeting.start_date == date(2026, 8, 24) and meeting.end_date == date(2026, 12, 12)


def test_cypress_code_without_suffix_matches_padded_number():
    out, _ = _search(71, "MATH 11")
    assert [s.section_id for s in out.sections] == ["10434"]
    assert out.sections[0].modality == "hybrid"
    assert [m.is_online for m in out.sections[0].meetings] == [False, True]


def test_cypress_does_not_see_fullerton_rows():
    out, _ = _search(71, "MATH 151")
    assert out.offered is False


def test_fullerton_in_person_rows():
    out, _ = _search(134, "MATH 151")
    assert [s.section_id for s in out.sections] == ["12522", "12523"]
    assert out.sections[0].meetings[0].days == ("M", "W")
    assert out.sections[0].course_code_as_listed == "MATH 151 F"


def test_fullerton_online_row():
    out, _ = _search(134, "MATH 100")
    assert [s.section_id for s in out.sections] == ["12493"]
    section = out.sections[0]
    assert section.modality == "async_online"
    assert section.meetings[0].is_online is True and section.meetings[0].start_local is None


def test_sections_file_is_fetched_once_per_college_search():
    session = _session()
    _search(134, "MATH 151", session=session)
    provider = _provider(session)
    for code in ("MATH 151", "MATH 100", "CSCI 123"):
        provider.search_course(source=get_college_source(134), term=parse_term_label("Fall 2026"), course_code=code)
    urls = [c["url"] for c in session.calls]
    assert urls.count(_TERMS_URL) == 2 and urls.count(_FALL_SECTIONS_URL) == 2  # one per provider instance


def test_spring_term_resolves_by_season_and_year():
    out, session = _search(134, "MATH 151", label="Spring 2027")
    assert session.calls[1]["url"] == _SPRING_SECTIONS_URL
    assert out.offered is False


def test_unlisted_term_is_term_not_listed():
    with pytest.raises(TermNotListedError, match="Summer 2027"):
        _search(134, "MATH 151", label="Summer 2027")
