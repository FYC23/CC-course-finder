from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from src.schedule.models import CollegeScheduleSource
from src.schedule.smcccd_colleague import SmcccdColleagueProvider
from src.schedule.term import parse_term_label

_SOURCE = CollegeScheduleSource(
    cc_id=5,
    cc_name="College of San Mateo",
    system="smcccd_colleague",
    base_url="https://api.smccd.edu/v1/schedule",
    locations=("college of san mateo",),
)

_BANNER = CollegeScheduleSource(
    cc_id=2,
    cc_name="Evergreen Valley College",
    system="banner",
    base_url="https://colss-prod.ec.sjeccd.edu/Student/Courses/SearchResult",
    locations=("EVC",),
)

_PAYLOAD = {
    "_embedded": {
        "course": [
            {
                "crn": "50123",
                "subject_code": "MATH",
                "course_number": "0115",
                "title": "Probability and Statistics",
                "status": "Open",
                "sections": [
                    {
                        "section_sequence": "01",
                        "schedule_description": "Web Based",
                        "location": {"college_description": "College of San Mateo"},
                        "instructor": {"name": "Doe, Jane"},
                    }
                ],
            },
            {
                "crn": "50333",
                "subject_code": "MATH",
                "course_number": "120",
                "title": "Precalculus",
                "status": "Open",
                "sections": [],
            },
        ]
    }
}


def _response(payload: dict, url: str) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.json.return_value = payload
    response.url = url
    response.raise_for_status = MagicMock()
    return response


def test_supports_smcccd_colleague():
    provider = SmcccdColleagueProvider()
    assert provider.supports_source(_SOURCE)
    assert not provider.supports_source(_BANNER)


def test_search_course_requires_credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SMCCD_API_USERNAME", raising=False)
    monkeypatch.delenv("SMCCD_API_PASSWORD", raising=False)
    provider = SmcccdColleagueProvider()
    term = parse_term_label("Spring 2026")
    with pytest.raises(ValueError, match="requires basic auth"):
        provider.search_course(source=_SOURCE, term=term, course_code="MATH 115")


def test_search_course_parses_matching_sections(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SMCCD_API_USERNAME", "user")
    monkeypatch.setenv("SMCCD_API_PASSWORD", "pass")

    session = MagicMock(spec=requests.Session)
    session.get.return_value = _response(
        _PAYLOAD,
        "https://api.smccd.edu/v1/schedule/courses?term_desc=Spring+2026",
    )
    provider = SmcccdColleagueProvider(session=session)
    term = parse_term_label("Spring 2026")
    result = provider.search_course(source=_SOURCE, term=term, course_code="MATH 115")

    assert result.offered is True
    assert len(result.sections) == 1
    assert result.sections[0].section_id == "50123-01"
    assert result.sections[0].status == "open"
    assert result.sections[0].modality == "online"
    assert result.sections[0].instructor == "Doe, Jane"
