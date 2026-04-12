"""Tests for BannerSsbClassicProvider."""
from __future__ import annotations

from unittest.mock import MagicMock
import pytest
import requests

from src.schedule.banner_ssb_classic import BannerSsbClassicProvider, _resolve_term_code
from src.schedule.models import CollegeScheduleSource
from src.schedule.term import parse_term_label

_MTSAC = CollegeScheduleSource(
    cc_id=62,
    cc_name="Mount San Antonio College",
    system="banner_ssb_classic",
    base_url="https://prodrg.mtsac.edu",
    locations=("MTSAC",),
)

_BANNER = CollegeScheduleSource(
    cc_id=2,
    cc_name="Evergreen Valley College",
    system="banner",
    base_url="https://colss-prod.ec.sjeccd.edu/Student/Courses/SearchResult",
    locations=("EVC",),
)

_TERMS = [
    {"code": "202610", "description": "Summer 2026"},
    {"code": "202540", "description": "Spring 2026"},
    {"code": "202520", "description": "Fall 2025 (View Only)"},
]

_SEARCH_TWO = {
    "totalCount": 2,
    "data": [
        {
            "courseReferenceNumber": "10263",
            "subject": "MATH",
            "courseNumber": "181",
            "courseTitle": "Calculus II",
            "seatsAvailable": 1,
            "openSection": True,
        },
        {
            "courseReferenceNumber": "10264",
            "subject": "MATH",
            "courseNumber": "181",
            "courseTitle": "Calculus II",
            "seatsAvailable": 0,
            "openSection": False,
        },
    ],
}

_SEARCH_EMPTY = {"totalCount": 0, "data": None}


def _make_resp(json_data, status=200, url="https://prodrg.mtsac.edu/StudentRegistrationSsb/ssb/searchResults/searchResults"):
    r = MagicMock(spec=requests.Response)
    r.status_code = status
    r.json.return_value = json_data
    r.url = url
    r.raise_for_status = MagicMock()
    return r


def _make_session(terms=_TERMS, search=_SEARCH_TWO):
    s = MagicMock(spec=requests.Session)
    s.headers = {}
    terms_resp = _make_resp(terms)
    post_resp = _make_resp({})
    search_resp = _make_resp(search)
    # get calls: getTerms, termSelection, search results
    s.get.side_effect = [terms_resp, _make_resp({}), search_resp]
    s.post.return_value = post_resp
    return s


# ---------------------------------------------------------------------------
# supports_source
# ---------------------------------------------------------------------------

def test_supports_banner_ssb_classic():
    assert BannerSsbClassicProvider().supports_source(_MTSAC)


def test_rejects_banner_system():
    assert not BannerSsbClassicProvider().supports_source(_BANNER)


# ---------------------------------------------------------------------------
# _resolve_term_code
# ---------------------------------------------------------------------------

def test_resolve_term_code_exact():
    s = MagicMock(spec=requests.Session)
    s.get.return_value = _make_resp(_TERMS)
    term = parse_term_label("Summer 2026")
    code = _resolve_term_code(s, "https://prodrg.mtsac.edu", term)
    assert code == "202610"


def test_resolve_term_code_strips_view_only():
    s = MagicMock(spec=requests.Session)
    s.get.return_value = _make_resp(_TERMS)
    term = parse_term_label("Fall 2025")
    code = _resolve_term_code(s, "https://prodrg.mtsac.edu", term)
    assert code == "202520"


def test_resolve_term_code_not_found():
    s = MagicMock(spec=requests.Session)
    s.get.return_value = _make_resp(_TERMS)
    term = parse_term_label("Spring 2099")
    with pytest.raises(ValueError, match="Spring 2099"):
        _resolve_term_code(s, "https://prodrg.mtsac.edu", term)


# ---------------------------------------------------------------------------
# search_course — happy path
# ---------------------------------------------------------------------------

def test_search_course_returns_sections():
    s = _make_session()
    p = BannerSsbClassicProvider(session=s)
    term = parse_term_label("Summer 2026")
    result = p.search_course(source=_MTSAC, term=term, course_code="MATH 181")
    assert result.offered is True
    assert len(result.sections) == 2
    assert result.sections[0].status == "open"
    assert result.sections[1].status == "closed"
    assert result.sections[0].section_id == "10263"


def test_search_course_empty_returns_not_offered():
    s = _make_session(search=_SEARCH_EMPTY)
    # get calls: termSelection, getTerms, search
    s.get.side_effect = [_make_resp(_TERMS), _make_resp({}), _make_resp(_SEARCH_EMPTY)]
    p = BannerSsbClassicProvider(session=s)
    term = parse_term_label("Summer 2026")
    result = p.search_course(source=_MTSAC, term=term, course_code="MATH 999")
    assert result.offered is False
    assert result.sections == []


def test_search_course_sets_cc_metadata():
    s = _make_session()
    p = BannerSsbClassicProvider(session=s)
    term = parse_term_label("Summer 2026")
    result = p.search_course(source=_MTSAC, term=term, course_code="MATH 181")
    assert result.cc_id == 62
    assert result.cc_name == "Mount San Antonio College"
    assert result.term == "Summer 2026"
    assert result.course_code == "MATH 181"


# ---------------------------------------------------------------------------
# Term code caching
# ---------------------------------------------------------------------------

def test_term_code_cached_across_calls():
    s = _make_session()
    # Second call: termSelection + search only (no getTerms)
    s.get.side_effect = [
        _make_resp(_TERMS),      # getTerms call 1
        _make_resp({}),          # termSelection call 1
        _make_resp(_SEARCH_TWO), # search call 1
        _make_resp({}),          # termSelection call 2 (no getTerms — cached)
        _make_resp(_SEARCH_TWO), # search call 2
    ]
    p = BannerSsbClassicProvider(session=s)
    term = parse_term_label("Summer 2026")
    p.search_course(source=_MTSAC, term=term, course_code="MATH 181")
    p.search_course(source=_MTSAC, term=term, course_code="MATH 182")
    # getTerms called exactly once
    get_calls = [str(c) for c in s.get.call_args_list]
    terms_calls = [c for c in get_calls if "getTerms" in c]
    assert len(terms_calls) == 1


# ---------------------------------------------------------------------------
# supports_source rejects wrong system
# ---------------------------------------------------------------------------

def test_search_course_raises_for_wrong_system():
    p = BannerSsbClassicProvider()
    term = parse_term_label("Summer 2026")
    with pytest.raises(ValueError, match="does not support"):
        p.search_course(source=_BANNER, term=term, course_code="MATH 1")
