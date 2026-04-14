from __future__ import annotations

import json

from src.schedule.models import CollegeScheduleSource
from src.schedule.term import parse_term_label
from src.schedule.wvm_static import WvmStaticProvider


class _FakeResponse:
    def __init__(self, *, json_obj: list | dict) -> None:
        self._json = json_obj
        self.text = json.dumps(json_obj)

    def raise_for_status(self) -> None:
        return None

    def json(self) -> list | dict:
        return self._json


class _FakeSession:
    def __init__(self, *, get_responses: list[_FakeResponse]) -> None:
        self._get_responses = get_responses
        self.calls: list[str] = []

    def get(self, url: str, timeout: int) -> _FakeResponse:
        self.calls.append(url)
        return self._get_responses.pop(0)


_WVM_SOURCE = CollegeScheduleSource(
    cc_id=80,
    cc_name="West Valley College",
    system="wvm_static",
    base_url="https://schedule.wvm.edu",
    locations=("WVC",),
)

_CRNS_PAYLOAD = [
    {
        "CRN": "70001",
        "SUBJ_CODE": "MATH",
        "CRSE_NUMB": "1B",
        "CRSE_TITLE": "Calculus II",
        "SSBSECT_INSM_CODE": "INP",
        "SSBSECT_SEATS_AVAIL": 5,
        "SSBSECT_CAMP_CODE": "WVC",
    },
    {
        "CRN": "70002",
        "SUBJ_CODE": "MATH",
        "CRSE_NUMB": "1B",
        "CRSE_TITLE": "Calculus II",
        "SSBSECT_INSM_CODE": "AON",
        "SSBSECT_SEATS_AVAIL": 0,
        "SSBSECT_CAMP_CODE": "WVC",
    },
    {
        "CRN": "70003",
        "SUBJ_CODE": "ENGL",
        "CRSE_NUMB": "001A",
        "CRSE_TITLE": "English Composition",
        "SSBSECT_INSM_CODE": "HYB",
        "SSBSECT_SEATS_AVAIL": 3,
        "SSBSECT_CAMP_CODE": "WVC",
    },
]

_INSTRUCTORS_PAYLOAD = [
    {"SIRASGN_CRN": "70001", "INSTRUCTOR_NAME": "Ada Lovelace"},
    {"SIRASGN_CRN": "70002", "INSTRUCTOR_NAME": "Bob Babbage"},
    {"SIRASGN_CRN": "70003", "INSTRUCTOR_NAME": "Grace Hopper"},
]


def test_found_open_section() -> None:
    session = _FakeSession(
        get_responses=[
            _FakeResponse(json_obj=_CRNS_PAYLOAD),
            _FakeResponse(json_obj=_INSTRUCTORS_PAYLOAD),
        ]
    )
    provider = WvmStaticProvider(session=session)
    out = provider.search_course(
        source=_WVM_SOURCE,
        term=parse_term_label("Spring 2026"),
        course_code="MATH 1B",
    )

    assert out.offered is True
    assert len(out.sections) == 2
    open_sec = next(s for s in out.sections if s.section_id == "70001")
    assert open_sec.status == "open"
    assert open_sec.modality == "in_person"
    assert open_sec.instructor == "Ada Lovelace"
    closed_sec = next(s for s in out.sections if s.section_id == "70002")
    assert closed_sec.status == "closed"
    assert closed_sec.modality == "online"
    assert out.source_url == "https://schedule.wvm.edu/data/202630/crns.json"


def test_not_offered() -> None:
    session = _FakeSession(
        get_responses=[
            _FakeResponse(json_obj=_CRNS_PAYLOAD),
        ]
    )
    provider = WvmStaticProvider(session=session)
    out = provider.search_course(
        source=_WVM_SOURCE,
        term=parse_term_label("Spring 2026"),
        course_code="PHYS 4A",
    )

    assert out.offered is False
    assert out.sections == []
    # instructor endpoint NOT fetched — only 1 GET call
    assert len(session.calls) == 1


def test_supports_source() -> None:
    provider = WvmStaticProvider()
    assert provider.supports_source(_WVM_SOURCE) is True
    banner_source = CollegeScheduleSource(
        cc_id=2,
        cc_name="Evergreen Valley College",
        system="banner",
        base_url="https://example.com",
        locations=("EVC",),
    )
    assert provider.supports_source(banner_source) is False


def test_crse_numb_leading_zeros_match() -> None:
    """ENGL 1A should match CRSE_NUMB='001A'."""
    session = _FakeSession(
        get_responses=[
            _FakeResponse(json_obj=_CRNS_PAYLOAD),
            _FakeResponse(json_obj=_INSTRUCTORS_PAYLOAD),
        ]
    )
    provider = WvmStaticProvider(session=session)
    out = provider.search_course(
        source=_WVM_SOURCE,
        term=parse_term_label("Fall 2026"),
        course_code="ENGL 1A",
    )

    assert out.offered is True
    assert out.sections[0].instructor == "Grace Hopper"
    assert out.sections[0].modality == "hybrid"


def test_location_filter_excludes_other_campus() -> None:
    """MC (Mission College) rows excluded when source.locations=('WVC',)."""
    crns_mixed = [
        {
            "CRN": "70010",
            "SUBJ_CODE": "MATH",
            "CRSE_NUMB": "1B",
            "CRSE_TITLE": "Calculus II",
            "SSBSECT_INSM_CODE": "INP",
            "SSBSECT_SEATS_AVAIL": 5,
            "SSBSECT_CAMP_CODE": "WVC",
        },
        {
            "CRN": "70011",
            "SUBJ_CODE": "MATH",
            "CRSE_NUMB": "1B",
            "CRSE_TITLE": "Calculus II",
            "SSBSECT_INSM_CODE": "INP",
            "SSBSECT_SEATS_AVAIL": 8,
            "SSBSECT_CAMP_CODE": "MC",
        },
    ]
    instructors = [
        {"SIRASGN_CRN": "70010", "INSTRUCTOR_NAME": "Ada Lovelace"},
        {"SIRASGN_CRN": "70011", "INSTRUCTOR_NAME": "Mission Instructor"},
    ]
    session = _FakeSession(
        get_responses=[
            _FakeResponse(json_obj=crns_mixed),
            _FakeResponse(json_obj=instructors),
        ]
    )
    provider = WvmStaticProvider(session=session)
    out = provider.search_course(
        source=_WVM_SOURCE,
        term=parse_term_label("Summer 2026"),
        course_code="MATH 1B",
    )

    assert out.offered is True
    assert len(out.sections) == 1
    assert out.sections[0].section_id == "70010"
    assert out.sections[0].instructor == "Ada Lovelace"
