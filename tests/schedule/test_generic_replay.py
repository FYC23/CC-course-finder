from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

import pytest

from src.schedule.errors import PortalChanged
from src.schedule.generic_replay import GenericReplayProvider
from src.schedule.models import CollegeScheduleSource
from src.schedule.replay.executor import HostThrottle, ReplayExecutor
from src.schedule.replay.spec import load_spec
from src.schedule.term import TermNotListedError, parse_term_label
from tests.schedule.replay.fakes import FakeSession

_SPEC = {
    "cc_id": 999, "cc_name": "Test College", "version": 1, "recorded_at": "2026-09-23",
    "probe": {"course_code": "MATH 1", "term": "Fall 2026"},
    "inputs": {"term": {"format": "{yyyy}{SEASON}", "seasons": {"fall": "70"}}},
    "steps": [{"id": "search", "method": "GET", "url": "https://example.edu/api",
               "query": {"term": "{term}", "subj": "{subject}", "num": "{number}"}}],
    "extract": {"kind": "json", "rows": "$.data[*]",
                "fields": {"section_id": "$.crn", "title": "$.title", "seats_available": "$.avail"},
                "status": {"from_seats": True}},
}
_SOURCE = CollegeScheduleSource(cc_id=999, cc_name="Test College", system="replay",
                                base_url="https://example.edu", locations=())
_OTHER = CollegeScheduleSource(cc_id=62, cc_name="Mt SAC", system="banner9_ssb",
                               base_url="https://prodrg.mtsac.edu", locations=())
_FALL = parse_term_label("Fall 2026")


@pytest.fixture
def spec(tmp_path: Path):
    path = tmp_path / "999.json"
    path.write_text(json.dumps(_SPEC))
    return load_spec(path)


def _provider(spec, session: FakeSession) -> GenericReplayProvider:
    executor = ReplayExecutor(session, throttle=HostThrottle(0.0), sleeper=lambda s: None)
    return GenericReplayProvider(executor=executor, specs=MappingProxyType({999: spec}))


def test_supports_only_replay_sources_with_a_spec(spec):
    provider = _provider(spec, FakeSession({}))
    assert provider.supports_source(_SOURCE)
    assert not provider.supports_source(_OTHER)
    unknown = CollegeScheduleSource(cc_id=1, cc_name="X", system="replay", base_url="https://x", locations=())
    assert not provider.supports_source(unknown)


def test_search_course_returns_sections(spec):
    body = json.dumps({"data": [{"crn": "1", "title": "Calc", "avail": 3}, {"crn": "2", "title": "Calc", "avail": 0}]})
    session = FakeSession({"https://example.edu/api": body})
    out = _provider(spec, session).search_course(source=_SOURCE, term=_FALL, course_code="MATH 1")
    assert out.offered is True
    assert [s.section_id for s in out.sections] == ["1", "2"]
    assert [s.status for s in out.sections] == ["open", "closed"]
    assert out.cc_id == 999 and out.cc_name == "Test College"
    assert out.term == "Fall 2026" and out.course_code == "MATH 1"
    assert out.source_url == "https://example.edu/api"
    assert "2 section(s)" in out.raw_summary and out.lookup_error is None
    assert session.calls[0]["params"] == {"term": "202670", "subj": "MATH", "num": "1"}


def test_search_course_no_rows_is_not_offered(spec):
    session = FakeSession({"https://example.edu/api": json.dumps({"data": []})})
    out = _provider(spec, session).search_course(source=_SOURCE, term=_FALL, course_code="MATH 1")
    assert out.offered is False and out.sections == []


def test_search_course_wrong_system_raises(spec):
    with pytest.raises(ValueError, match="does not support"):
        _provider(spec, FakeSession({})).search_course(source=_OTHER, term=_FALL, course_code="MATH 1")


def test_portal_changed_propagates(spec):
    session = FakeSession({"https://example.edu/api": json.dumps({"nope": []})})
    with pytest.raises(PortalChanged):
        _provider(spec, session).search_course(source=_SOURCE, term=_FALL, course_code="MATH 1")


def test_unknown_season_is_term_not_listed(spec):
    with pytest.raises(TermNotListedError):
        _provider(spec, FakeSession({})).search_course(
            source=_SOURCE, term=parse_term_label("Spring 2027"), course_code="MATH 1")


def test_default_constructor_loads_committed_specs():
    provider = GenericReplayProvider()
    assert not provider.supports_source(_OTHER)
