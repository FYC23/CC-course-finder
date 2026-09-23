from __future__ import annotations

from src.schedule.colleague_selfservice import ColleagueSelfServiceProvider
from src.schedule.models import CollegeScheduleSource

_BANNER_SOURCE = CollegeScheduleSource(
    cc_id=2,
    cc_name="Evergreen Valley College",
    system="colleague_selfservice",
    base_url="https://colss-prod.ec.sjeccd.edu/Student/Courses/SearchResult",
    locations=("EVC",),
)

_NON_BANNER_SOURCE = CollegeScheduleSource(
    cc_id=4,
    cc_name="College of Marin",
    system="marin_colleague",
    base_url="https://netapps.marin.edu/Apps/Directory/ScheduleSearch.aspx",
    locations=("0000",),
)


def test_supports_banner_source():
    provider = ColleagueSelfServiceProvider()
    assert provider.supports_source(_BANNER_SOURCE)


def test_rejects_non_banner_source():
    provider = ColleagueSelfServiceProvider()
    assert not provider.supports_source(_NON_BANNER_SOURCE)


from types import MappingProxyType  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402
import requests  # noqa: E402

from src.schedule.colleague_selfservice import (  # noqa: E402
    extract_request_token,
    format_term_code,
    resolve_term_code,
)
from src.schedule.term import parse_term_label  # noqa: E402

_HTML = '<form><input name="__RequestVerificationToken" type="hidden" value="CfDJ8ABC" /></form>'
_HTML_REVERSED = '<input type="hidden" value="CfDJ8XYZ" name="__RequestVerificationToken">'


def test_extract_request_token():
    assert extract_request_token(_HTML) == "CfDJ8ABC"
    assert extract_request_token(_HTML_REVERSED) == "CfDJ8XYZ"
    assert extract_request_token("<html></html>") is None


@pytest.mark.parametrize(
    "fmt,expected",
    [
        ("{yyyy}{SEASON2}", "2026FA"),
        ("{yyyy}/{SEASON2}", "2026/FA"),
        ("{yyyy}{SEASON1}", "2026F"),
        ("{yy}/{SEASON2}", "26/FA"),
    ],
)
def test_format_term_code(fmt, expected):
    assert format_term_code(parse_term_label("Fall 2026"), fmt) == expected


def test_format_term_code_seasons():
    assert format_term_code(parse_term_label("Spring 2027"), "{yyyy}{SEASON2}") == "2027SP"
    assert format_term_code(parse_term_label("Summer 2026"), "{yyyy}{SEASON1}") == "2026U"


def _resp(json_data, text="", status=200):
    r = MagicMock(spec=requests.Response)
    r.status_code = status
    r.json.return_value = json_data
    r.text = text
    r.url = "https://example.edu/Student/Courses/PostSearchCriteria"
    r.raise_for_status = MagicMock()
    return r


def test_resolve_term_code_matches_description():
    session = MagicMock(spec=requests.Session)
    session.post.return_value = _resp(
        {"TermFilters": [{"Value": "2026FA", "Description": "Fall 2026 Regular"},
                         {"Value": "2026SU", "Description": "Summer 2026 Regular"}]}
    )
    code = resolve_term_code(session, "https://example.edu", parse_term_label("Fall 2026"), keyword="MATH 1", headers={})
    assert code == "2026FA"


def test_resolve_term_code_missing_raises():
    session = MagicMock(spec=requests.Session)
    session.post.return_value = _resp({"TermFilters": [{"Value": "2026SU", "Description": "Summer 2026"}]})
    with pytest.raises(ValueError, match="Fall 2026"):
        resolve_term_code(session, "https://example.edu", parse_term_label("Fall 2026"), keyword="MATH 1", headers={})


def test_supports_source_with_empty_locations():
    src = CollegeScheduleSource(cc_id=73, cc_name="Napa Valley College", system="colleague_selfservice",
                                base_url="https://colss-prod.ec.napavalley.edu", locations=())
    assert ColleagueSelfServiceProvider().supports_source(src)


def test_search_uses_term_format_override_and_sends_token():
    src = CollegeScheduleSource(
        cc_id=69, cc_name="Chaffey College", system="colleague_selfservice",
        base_url="https://colss-prod.ec.chaffey.edu", locations=(),
        params=MappingProxyType({"term_format": "{yyyy}/{SEASON2}"}),
    )
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.get.return_value = _resp({}, text=_HTML)
    listing = {"TotalPages": 1, "Sections": [{
        "Synonym": "1", "CourseName": "MATH-25", "Title": "Calc", "AvailabilityStatusDisplay": "Open",
        "Capacity": 30, "Enrolled": 10, "InstructionalMethodsDisplay": ["Lecture"], "FacultyDisplay": ["A B"],
        "FormattedMeetingTimes": [{"Days": [2, 4], "StartTime": "09:00:00", "EndTime": "10:15:00", "IsOnline": False,
                                    "BuildingDisplay": "H", "RoomDisplay": "101"}],
        "Course": {"SubjectCode": "MATH", "Number": "25"}}]}
    session.post.return_value = _resp(listing)
    provider = ColleagueSelfServiceProvider(session=session)
    result = provider.search_course(source=src, term=parse_term_label("Fall 2026"), course_code="MATH 25")
    assert result.offered is True
    assert result.sections[0].meetings[0].days == ("T", "R")
    assert result.sections[0].seats_used == 10
    payload = session.post.call_args_list[0].kwargs["json"]
    assert payload["terms"] == ["2026/FA"]
    assert payload["locations"] == []
    assert (
        session.post.call_args_list[0].kwargs["headers"]["__RequestVerificationToken"]
        == "CfDJ8ABC"
    )


def test_search_filters_by_location_match_when_locations_empty():
    src = CollegeScheduleSource(
        cc_id=67, cc_name="West Hills College Coalinga", system="colleague_selfservice",
        base_url="https://ellucianssui.whccd.edu", locations=(),
        params=MappingProxyType({"term_format": "{yyyy}/{SEASON2}", "location_match": "Coalinga"}),
    )
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.get.return_value = _resp({}, text=_HTML)
    base = {"CourseName": "MATH-25", "Title": "Calc", "AvailabilityStatusDisplay": "Open",
            "Course": {"SubjectCode": "MATH", "Number": "25"}, "FormattedMeetingTimes": []}
    listing = {"TotalPages": 1, "Sections": [
        {**base, "Synonym": "1", "LocationDisplay": "West Hills College Coalinga"},
        {**base, "Synonym": "2", "LocationDisplay": "West Hills College Lemoore"}]}
    session.post.return_value = _resp(listing)
    result = ColleagueSelfServiceProvider(session=session).search_course(
        source=src, term=parse_term_label("Fall 2026"), course_code="MATH 25")
    assert [s.section_id for s in result.sections] == ["1"]


def test_bootstrap_isolates_token_across_colleges():
    """Regression: one provider (and one requests.Session) is reused across every college in
    ScheduleService.query. The token for college A must never leak onto college B's requests,
    and the shared session.headers must never be mutated at all."""
    src_a = CollegeScheduleSource(
        cc_id=90, cc_name="College A", system="colleague_selfservice",
        base_url="https://colss-a.example.edu", locations=(),
        params=MappingProxyType({"term_format": "{yyyy}{SEASON2}"}),
    )
    src_b = CollegeScheduleSource(
        cc_id=91, cc_name="College B", system="colleague_selfservice",
        base_url="https://colss-b.example.edu", locations=(),
        params=MappingProxyType({"term_format": "{yyyy}{SEASON2}"}),
    )
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.get.side_effect = [_resp({}, text=_HTML), _resp({}, text="<html></html>")]
    matching_section = {
        "Synonym": "1", "CourseName": "MATH-25", "Title": "Calc", "AvailabilityStatusDisplay": "Open",
        "Course": {"SubjectCode": "MATH", "Number": "25"}, "FormattedMeetingTimes": [],
    }
    session.post.return_value = _resp({"TotalPages": 1, "Sections": [matching_section]})
    provider = ColleagueSelfServiceProvider(session=session)

    provider.search_course(source=src_a, term=parse_term_label("Fall 2026"), course_code="MATH 25")
    calls_after_a = len(session.post.call_args_list)
    assert (
        session.post.call_args_list[0].kwargs["headers"]["__RequestVerificationToken"]
        == "CfDJ8ABC"
    )

    provider.search_course(source=src_b, term=parse_term_label("Fall 2026"), course_code="MATH 25")
    for call in session.post.call_args_list[calls_after_a:]:
        assert "__RequestVerificationToken" not in call.kwargs.get("headers", {})

    assert "__RequestVerificationToken" not in session.headers
