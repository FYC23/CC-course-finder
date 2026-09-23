"""Every adapter must emit modality values from the shared models.MODALITIES enum.

Reuses each adapter's own test fakes/fixtures so this file stays a thin cross-check
rather than a second copy of each adapter's fixture data.
"""
from __future__ import annotations

from src.schedule import models
from src.schedule.banner9_ssb import Banner9SsbProvider
from src.schedule.colleague_selfservice import ColleagueSelfServiceProvider
from src.schedule.term import parse_term_label
from src.schedule.vsb_4cd import Vsb4cdProvider
from src.schedule.wvm_static import WvmStaticProvider

from tests.schedule.test_banner9_ssb import (
    _MTSAC,
    _ROW_IN_PERSON,
    _ROW_ONLINE,
    _make_resp as _banner_resp,
)
from tests.schedule.test_pilot_provider import (
    _FakeResponse as _ColleagueResp,
    _FakeSession as _ColleagueSession,
    _term_filters_response,
)
from tests.schedule.test_vsb_4cd import _LMC, _XML_TWO_SECTIONS, _make_session as _make_vsb_session
from tests.schedule.test_wvm_provider import (
    _CRNS_PAYLOAD,
    _INSTRUCTORS_PAYLOAD,
    _WVM_SOURCE,
    _FakeResponse as _WvmResp,
    _FakeSession as _WvmSession,
)


def test_wvm_static_modalities_are_in_enum():
    session = _WvmSession(
        get_responses=[
            _WvmResp(json_obj=_CRNS_PAYLOAD),
            _WvmResp(json_obj=_INSTRUCTORS_PAYLOAD),
        ]
    )
    provider = WvmStaticProvider(session=session)
    out = provider.search_course(
        source=_WVM_SOURCE, term=parse_term_label("Spring 2026"), course_code="MATH 1B"
    )
    assert out.sections
    for section in out.sections:
        assert section.modality in models.MODALITIES


def test_vsb_4cd_modalities_are_in_enum():
    session = _make_vsb_session(_XML_TWO_SECTIONS)
    provider = Vsb4cdProvider(session=session)
    out = provider.search_course(
        source=_LMC, term=parse_term_label("Summer 2026"), course_code="MATH 220"
    )
    assert out.sections
    for section in out.sections:
        assert section.modality in models.MODALITIES


def test_banner9_ssb_modalities_are_in_enum():
    from unittest.mock import MagicMock
    import requests

    terms = [{"code": "202610", "description": "Summer 2026"}]
    s = MagicMock(spec=requests.Session)
    s.headers = {}
    s.get.side_effect = [
        _banner_resp(terms),
        _banner_resp({}),
        _banner_resp({"totalCount": 2, "data": [_ROW_IN_PERSON, _ROW_ONLINE]}),
    ]
    s.post.return_value = _banner_resp({})
    provider = Banner9SsbProvider(session=s)
    out = provider.search_course(
        source=_MTSAC, term=parse_term_label("Summer 2026"), course_code="MATH 180"
    )
    assert out.sections
    for section in out.sections:
        assert section.modality in models.MODALITIES


def test_colleague_selfservice_modalities_are_in_enum():
    from src.schedule.catalog import get_college_source

    source = get_college_source(2)
    section_listing_payload = {
        "Sections": [
            {
                "Synonym": "12345",
                "AvailabilityStatusDisplay": "Open",
                "InstructionalMethodsDisplay": ["Online, Asynchronous"],
                "Title": "Calculus II",
                "CourseName": "MATH-1B",
                "FacultyDisplay": ["Ada Lovelace"],
            },
            {
                "Synonym": "12346",
                "AvailabilityStatusDisplay": "Closed",
                "InstructionalMethodsDisplay": ["Lecture"],
                "Title": "Calculus II",
                "CourseName": "MATH-1B",
                "FacultyDisplay": ["Bob Babbage"],
            },
        ]
    }
    session = _ColleagueSession(
        get_responses=[
            _ColleagueResp(
                text="bootstrap ok",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/Search",
            )
        ],
        post_responses=[
            _term_filters_response(),
            _ColleagueResp(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj=section_listing_payload,
            ),
        ],
    )
    provider = ColleagueSelfServiceProvider(session=session)
    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 1B"
    )
    assert out.sections
    for section in out.sections:
        assert section.modality in models.MODALITIES
