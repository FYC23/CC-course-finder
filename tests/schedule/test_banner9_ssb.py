"""Tests for Banner9SsbProvider."""
from __future__ import annotations

from src.schedule.term import TermNotListedError

from unittest.mock import MagicMock
import pytest
import requests

from src.schedule.banner9_ssb import Banner9SsbProvider, _resolve_term_code
from src.schedule.models import CollegeScheduleSource
from src.schedule.term import parse_term_label

_MTSAC = CollegeScheduleSource(
    cc_id=62,
    cc_name="Mount San Antonio College",
    system="banner9_ssb",
    base_url="https://prodrg.mtsac.edu",
    locations=("MTSAC",),
)

_BANNER = CollegeScheduleSource(
    cc_id=2,
    cc_name="Evergreen Valley College",
    system="colleague_selfservice",
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

def test_supports_banner9_ssb():
    assert Banner9SsbProvider().supports_source(_MTSAC)


def test_rejects_banner_system():
    assert not Banner9SsbProvider().supports_source(_BANNER)


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
    with pytest.raises(TermNotListedError, match="Spring 2099"):
        _resolve_term_code(s, "https://prodrg.mtsac.edu", term)


def test_resolve_term_code_matches_season_and_year_tokens():
    """Feather River-style description embeds the term inside a longer descriptive string:
    "Fall Term 2026 202710 12-AUG-2026 - 09-DEC-2026". No exact or prefix match exists, so
    this falls back to matching the season word and year as separate tokens."""
    s = MagicMock(spec=requests.Session)
    s.get.return_value = _make_resp(
        [{"code": "202710", "description": "Fall Term 2026 202710 12-AUG-2026 - 09-DEC-2026"}]
    )
    term = parse_term_label("Fall 2026")
    code = _resolve_term_code(s, "https://prodrg.mtsac.edu", term)
    assert code == "202710"


def test_resolve_term_code_exact_beats_token_only_match():
    """An earlier token-only match (rank 3) must lose to a later exact match (rank 0)."""
    s = MagicMock(spec=requests.Session)
    s.get.return_value = _make_resp(
        [
            {"code": "111", "description": "Fall Term 2026 202710 12-AUG-2026 - 09-DEC-2026"},
            {"code": "202710", "description": "Fall 2026"},
        ]
    )
    term = parse_term_label("Fall 2026")
    code = _resolve_term_code(s, "https://prodrg.mtsac.edu", term)
    assert code == "202710"


# ---------------------------------------------------------------------------
# search_course — happy path
# ---------------------------------------------------------------------------

def test_search_course_returns_sections():
    s = _make_session()
    p = Banner9SsbProvider(session=s)
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
    p = Banner9SsbProvider(session=s)
    term = parse_term_label("Summer 2026")
    result = p.search_course(source=_MTSAC, term=term, course_code="MATH 999")
    assert result.offered is False
    assert result.sections == []


def test_search_course_sets_cc_metadata():
    s = _make_session()
    p = Banner9SsbProvider(session=s)
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
    p = Banner9SsbProvider(session=s)
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
    p = Banner9SsbProvider()
    term = parse_term_label("Summer 2026")
    with pytest.raises(ValueError, match="does not support"):
        p.search_course(source=_BANNER, term=term, course_code="MATH 1")


def test_search_course_search_request_error_does_not_mask_exception():
    s = MagicMock(spec=requests.Session)
    s.headers = {}
    s.get.side_effect = [
        _make_resp(_TERMS),
        _make_resp({}),
        requests.RequestException("network down"),
    ]
    s.post.return_value = _make_resp({})
    p = Banner9SsbProvider(session=s)
    term = parse_term_label("Summer 2026")

    with pytest.raises(requests.RequestException, match="network down"):
        p.search_course(source=_MTSAC, term=term, course_code="MATH 181")


# ---------------------------------------------------------------------------
# Row parsing: meetings, faculty, seats, modality, campus filter
# ---------------------------------------------------------------------------

from datetime import date, time  # noqa: E402

from src.schedule.banner9_ssb import _parse_meeting, _parse_row, _row_matches_campus  # noqa: E402
from src.schedule.models import CollegeScheduleSource as _Src  # noqa: E402

_ROW_IN_PERSON = {
    "courseReferenceNumber": "21216", "subject": "MATH", "courseNumber": "180",
    "subjectCourse": "MATH180", "courseTitle": "Calculus and Analytic Geometry",
    "openSection": True, "seatsAvailable": -4, "maximumEnrollment": 40, "enrollment": 36,
    "waitCapacity": 10, "waitCount": 4,
    "instructionalMethod": "02", "instructionalMethodDescription": "Lecture and/or Discussion",
    "campusDescription": "Mt. San Antonio College",
    "faculty": [{"displayName": "Nguyen, Bao-Chi T", "primaryIndicator": True}],
    "meetingsFaculty": [{"meetingTime": {
        "beginTime": "0730", "endTime": "0935", "building": "61", "buildingDescription": "Bldg 61",
        "room": "2306", "campus": "MS", "startDate": "08/24/2026", "endDate": "12/13/2026",
        "monday": True, "tuesday": False, "wednesday": True, "thursday": False,
        "friday": False, "saturday": False, "sunday": False, "meetingType": "CLAS"}}],
}

_ROW_ONLINE = {
    "courseReferenceNumber": "22001", "subject": "MATH", "courseNumber": "180",
    "subjectCourse": "MATH180", "courseTitle": "Calculus and Analytic Geometry",
    "openSection": True, "seatsAvailable": 5, "maximumEnrollment": 40, "enrollment": 35,
    "waitCapacity": 0, "waitCount": 0,
    "instructionalMethod": "OL", "instructionalMethodDescription": "Online",
    "campusDescription": "Mt. San Antonio College",
    "faculty": [],
    "meetingsFaculty": [{"meetingTime": {
        "beginTime": None, "endTime": None, "building": None, "buildingDescription": None,
        "room": None, "campus": "MS", "startDate": "08/24/2026", "endDate": "12/13/2026",
        "monday": False, "tuesday": False, "wednesday": False, "thursday": False,
        "friday": False, "saturday": False, "sunday": False, "meetingType": "CLAS"}}],
}


def test_parse_meeting_in_person():
    m = _parse_meeting(_ROW_IN_PERSON["meetingsFaculty"][0]["meetingTime"])
    assert m.days == ("M", "W")
    assert m.start_local == time(7, 30)
    assert m.end_local == time(9, 35)
    assert m.location == "Bldg 61 2306"
    assert m.is_online is False
    assert m.start_date == date(2026, 8, 24)
    assert m.end_date == date(2026, 12, 13)


def test_parse_meeting_online_has_no_times():
    m = _parse_meeting(_ROW_ONLINE["meetingsFaculty"][0]["meetingTime"])
    assert m.days == ()
    assert m.start_local is None
    assert m.is_online is True


def test_parse_row_in_person():
    s = _parse_row(_ROW_IN_PERSON)
    assert s.section_id == "21216"
    assert s.title == "Calculus and Analytic Geometry"
    assert s.instructor == "Nguyen, Bao-Chi T"
    assert s.modality == "in_person"
    assert s.status == "waitlist"          # open flag but no seats and a waitlist
    assert s.seats_total == 40
    assert s.seats_used == 36
    assert s.course_code_as_listed == "MATH 180"
    assert len(s.meetings) == 1


def test_parse_row_online_async():
    s = _parse_row(_ROW_ONLINE)
    assert s.modality == "async_online"
    assert s.status == "open"
    assert s.instructor == ""


def test_parse_row_closed_when_not_open_and_no_waitlist():
    row = {**_ROW_ONLINE, "openSection": False, "seatsAvailable": 0, "waitCapacity": 0}
    assert _parse_row(row).status == "closed"


def test_row_matches_campus_by_meeting_campus_code():
    assert _row_matches_campus(_ROW_IN_PERSON, ("MS",)) is True
    assert _row_matches_campus(_ROW_IN_PERSON, ("BB", "BC")) is False


def test_row_matches_campus_keeps_rows_without_meetings():
    row = {**_ROW_ONLINE, "meetingsFaculty": []}
    assert _row_matches_campus(row, ("XX",)) is True


def test_search_course_applies_campus_filter_from_params():
    from types import MappingProxyType
    src = _Src(
        cc_id=84, cc_name="Bakersfield College", system="banner9_ssb",
        base_url="https://reg-prod.ec.kccd.edu", locations=(),
        params=MappingProxyType({"campus_codes": "BB,BC"}),
    )
    s = _make_session(search={"totalCount": 2, "data": [_ROW_IN_PERSON, {**_ROW_ONLINE, "meetingsFaculty": [{"meetingTime": {**_ROW_ONLINE["meetingsFaculty"][0]["meetingTime"], "campus": "BB"}}]}]})
    p = Banner9SsbProvider(session=s)
    result = p.search_course(source=src, term=parse_term_label("Summer 2026"), course_code="MATH 180")
    assert [x.section_id for x in result.sections] == ["22001"]


def test_search_course_sections_carry_meetings():
    s = _make_session(search={"totalCount": 1, "data": [_ROW_IN_PERSON]})
    p = Banner9SsbProvider(session=s)
    result = p.search_course(source=_MTSAC, term=parse_term_label("Summer 2026"), course_code="MATH 180")
    assert result.sections[0].meetings[0].days == ("M", "W")


def test_search_course_accepts_string_total_count():
    """Some portals serialize totalCount as a numeric string; it must not crash on
    int() conversion or on the int/str comparison that ends pagination."""
    s = _make_session(search={"totalCount": "2", "data": _SEARCH_TWO["data"]})
    p = Banner9SsbProvider(session=s)
    result = p.search_course(source=_MTSAC, term=parse_term_label("Summer 2026"), course_code="MATH 181")
    assert result.offered is True
    assert "totalCount=2" in result.raw_summary


def test_search_course_drops_rows_for_a_different_course_number():
    """Requesting MATH 180 must not also return MATH 181 rows the search endpoint
    happens to include."""
    other_course_row = {**_SEARCH_TWO["data"][0], "courseNumber": "181"}
    s = _make_session(search={"totalCount": 2, "data": [_ROW_IN_PERSON, other_course_row]})
    p = Banner9SsbProvider(session=s)
    result = p.search_course(source=_MTSAC, term=parse_term_label("Summer 2026"), course_code="MATH 180")
    assert [x.section_id for x in result.sections] == ["21216"]


def test_search_course_matches_leading_zero_padded_course_number():
    """'MATH 005A' should still match a courseNumber of '5A'."""
    row = {
        "courseReferenceNumber": "99999",
        "subject": "MATH",
        "courseNumber": "5A",
        "courseTitle": "Test Course",
        "seatsAvailable": 5,
        "openSection": True,
    }
    s = _make_session(search={"totalCount": 1, "data": [row]})
    p = Banner9SsbProvider(session=s)
    result = p.search_course(source=_MTSAC, term=parse_term_label("Summer 2026"), course_code="MATH 005A")
    assert [x.section_id for x in result.sections] == ["99999"]


def test_row_matches_requested_course_keeps_all_rows_when_no_number_requested():
    """A subject-only search (empty requested number, e.g. _parse_course_code returned
    None) must not filter out any row by course number."""
    from src.schedule.banner9_ssb import _row_matches_requested_course

    assert _row_matches_requested_course(
        {"subject": "MATH", "courseNumber": "181"}, subject="MATH", number=""
    )
    assert _row_matches_requested_course(
        {"subject": "MATH", "courseNumber": "005A"}, subject="MATH", number=""
    )


def test_row_matches_campus_tolerates_null_meeting_time():
    """TBA records have meetingTime: null; must not crash and row is kept."""
    row = {**_ROW_ONLINE, "meetingsFaculty": [{"meetingTime": None}]}
    assert _row_matches_campus(row, ("MS",)) is True


# ---------------------------------------------------------------------------
# list_subject
# ---------------------------------------------------------------------------

def test_list_subject_searches_the_whole_subject_and_dedupes_courses():
    s = _make_session()
    courses = Banner9SsbProvider(session=s).list_subject(
        source=_MTSAC, term=parse_term_label("Summer 2026"), subject="math")
    assert [(c.code, c.title) for c in courses] == [("MATH 181", "Calculus II")]
    search_params = s.get.call_args_list[2].kwargs["params"]
    assert (search_params["txt_subject"], search_params["txt_courseNumber"]) == ("MATH", "")
