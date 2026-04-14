from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from src.schedule.marin_colleague import MarinColleagueProvider, _resolve_term_code
from src.schedule.models import CollegeScheduleSource
from src.schedule.term import parse_term_label

_SOURCE = CollegeScheduleSource(
    cc_id=4,
    cc_name="College of Marin",
    system="marin_colleague",
    base_url="https://netapps.marin.edu/Apps/Directory/ScheduleSearch.aspx",
    locations=("0000",),
)

_OTHER = CollegeScheduleSource(
    cc_id=5,
    cc_name="College of San Mateo",
    system="smcccd_colleague",
    base_url="https://api.smccd.edu/v1/schedule",
    locations=("college of san mateo",),
)

_LANDING_HTML = """
<select id="MainContent_cboTerm">
  <option value="000000">All Terms</option>
  <option value="202610">Spring 2026</option>
  <option value="202660">Summer 2026</option>
</select>
"""

_RESULT_HTML = """
<table id="MainContent_grdSchedule">
  <tr class="clsGridHeader">
    <td>Term</td><td>Section (CRN)</td><td>Course</td><td>Level</td><td>Credit Units</td>
    <td>TextBooks</td><td>Dates</td><td>Days</td><td>Time</td><td>Campus</td><td>Room</td><td>Type</td><td>Instructor</td>
  </tr>
  <tr class="clsGridItem">
    <td>Spring 2026</td><td>13379</td><td>MATH 115 - Probability and Statistics</td><td>Credit</td>
    <td>3.000</td><td>ZTC</td><td>01/17/26-05/15/26</td><td>MW</td><td>09:40 AM-11:00 AM</td>
    <td>Kentfield</td><td>CSS 101</td><td>CLAS</td><td>Jane Doe</td>
  </tr>
  <tr class="clsGridItem">
    <td>Spring 2026</td><td>14400</td><td>STAT C1000 - Introduction to Statistics</td><td>Credit</td>
    <td>3.000</td><td></td><td>01/17/26-05/15/26</td><td>TuTh</td><td>09:40 AM-11:00 AM</td>
    <td>Online Asynchronous</td><td>ONLINE</td><td>WEB</td><td>Alex Roe</td>
  </tr>
</table>
"""


def _response(*, html: str, url: str) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.text = html
    resp.url = url
    resp.raise_for_status = MagicMock()
    return resp


def test_supports_only_marin_colleague():
    provider = MarinColleagueProvider()
    assert provider.supports_source(_SOURCE)
    assert not provider.supports_source(_OTHER)


def test_resolve_term_code_found():
    term = parse_term_label("Spring 2026")
    assert _resolve_term_code(_LANDING_HTML, term) == "202610"


def test_resolve_term_code_missing():
    term = parse_term_label("Fall 2026")
    with pytest.raises(ValueError, match="Fall 2026"):
        _resolve_term_code(_LANDING_HTML, term)


def test_search_course_filters_sections_to_requested_course():
    session = MagicMock(spec=requests.Session)
    session.get.side_effect = [
        _response(html=_LANDING_HTML, url=_SOURCE.base_url),
        _response(
            html=_RESULT_HTML,
            url=f"{_SOURCE.base_url}?TermCode=202610&CampusCode=0000&SessionCode=0&SubjectCode=MATH",
        ),
    ]
    provider = MarinColleagueProvider(session=session)

    term = parse_term_label("Spring 2026")
    result = provider.search_course(source=_SOURCE, term=term, course_code="MATH 115")

    assert result.offered is True
    assert len(result.sections) == 1
    assert result.sections[0].section_id == "13379"
    assert result.sections[0].modality == "in_person"
    assert result.sections[0].instructor == "Jane Doe"


def test_search_course_returns_empty_when_no_matching_course():
    session = MagicMock(spec=requests.Session)
    session.get.side_effect = [
        _response(html=_LANDING_HTML, url=_SOURCE.base_url),
        _response(html=_RESULT_HTML, url=_SOURCE.base_url),
    ]
    provider = MarinColleagueProvider(session=session)

    term = parse_term_label("Spring 2026")
    result = provider.search_course(source=_SOURCE, term=term, course_code="BIO 120")
    assert result.offered is False
    assert result.sections == []
