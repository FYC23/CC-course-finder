from __future__ import annotations

import json

from src.schedule.catalog import get_college_source
from src.schedule.pilot_evergreen import EvergreenBannerProvider
from src.schedule.term import parse_term_label


class _FakeResponse:
    def __init__(self, *, text: str, url: str, json_obj: dict[str, object] | None = None) -> None:
        self.text = text
        self.url = url
        self._json = json_obj
        if json_obj is not None and not text:
            self.text = json.dumps(json_obj)

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        if self._json is None:
            raise ValueError("no json payload configured")
        return self._json


class _FakeSession:
    def __init__(
        self,
        *,
        get_responses: list[_FakeResponse],
        post_responses: list[_FakeResponse],
    ) -> None:
        self._get_responses = get_responses
        self._post_responses = post_responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, params: dict[str, str], timeout: int) -> _FakeResponse:
        self.calls.append((url, params))
        return self._get_responses.pop(0)

    def post(self, url: str, json: dict[str, object], timeout: int) -> _FakeResponse:
        params = {k: str(v) for k, v in json.items()}
        self.calls.append((url, params))
        return self._post_responses.pop(0)


def test_pilot_provider_uses_json_search_and_parses_sections() -> None:
    source = get_college_source(2)
    section_listing_payload = {
        "Sections": [
            {
                "Synonym": "12345",
                "Number": "201",
                "AvailabilityStatusDisplay": "Open",
                "InstructionalMethodsDisplay": ["Online, Asynchronous"],
                "Title": "Calculus II",
                "FacultyDisplay": ["Ada Lovelace"],
            },
            {
                "Synonym": "12346",
                "Number": "202",
                "AvailabilityStatusDisplay": "Closed",
                "InstructionalMethodsDisplay": ["Lecture"],
                "Title": "Calculus II",
                "FacultyDisplay": ["Bob Babbage"],
            },
        ]
    }
    session = _FakeSession(
        get_responses=[
            _FakeResponse(
                text="bootstrap ok",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/Search",
            )
        ],
        post_responses=[
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj=section_listing_payload,
            )
        ],
    )
    provider = EvergreenBannerProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 1B"
    )

    assert out.offered is True
    assert len(out.sections) == 2
    assert out.sections[0].modality == "online"
    assert out.sections[1].status == "closed"
    assert session.calls[0][1]["Terms"] == "2026SU"
    assert session.calls[0][1]["locations"] == "EVC"
    assert session.calls[0][1]["keyword"] == "MATH 1B"
    assert session.calls[1][1]["searchResultsView"] == "SectionListing"


def test_pilot_provider_falls_back_to_sections_endpoint_when_needed() -> None:
    source = get_college_source(2)
    section_listing_payload = {"Sections": []}
    catalog_listing_payload = {
        "CourseFullModels": [{"Id": "course-1", "MatchingSectionIds": ["sec-1"]}]
    }
    sections_payload = {
        "SectionsRetrieved": {
            "TermsAndSections": [
                {
                    "Sections": [
                        {
                            "Section": {
                                "Synonym": "77777",
                                "AvailabilityStatusDisplay": "Open",
                                "InstructionalMethodsDisplay": ["Hybrid"],
                                "Title": "Linear Algebra",
                            },
                            "FacultyDisplay": "Grace Hopper",
                        }
                    ]
                }
            ]
        }
    }
    session = _FakeSession(
        get_responses=[
            _FakeResponse(
                text="bootstrap ok",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/Search",
            )
        ],
        post_responses=[
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj=section_listing_payload,
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj=catalog_listing_payload,
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/Sections",
                json_obj=sections_payload,
            ),
        ],
    )
    provider = EvergreenBannerProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="BIOLOGY"
    )
    assert out.offered is True
    assert out.sections[0].section_id == "77777"
    assert out.sections[0].modality == "hybrid"
    assert out.sections[0].instructor == "Grace Hopper"
    assert session.calls[2][1]["searchResultsView"] == "CatalogListing"


def test_pilot_provider_tries_keyword_variants_until_match() -> None:
    source = get_college_source(2)
    session = _FakeSession(
        get_responses=[
            _FakeResponse(
                text="bootstrap one",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/Search",
            ),
            _FakeResponse(
                text="bootstrap two",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/Search",
            ),
        ],
        post_responses=[
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={"Sections": []},
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={"CourseFullModels": []},
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={
                    "Sections": [
                        {
                            "Synonym": "90001",
                            "AvailabilityStatusDisplay": "Open",
                            "InstructionalMethodsDisplay": ["Online"],
                            "Title": "Precalculus",
                            "FacultyDisplay": ["Ada"],
                        }
                    ]
                },
            ),
        ],
    )
    provider = EvergreenBannerProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 067"
    )

    assert out.offered is True
    assert out.sections[0].section_id == "90001"
    assert session.calls[0][1]["keyword"] == "MATH 067"
    assert session.calls[3][1]["keyword"] == "MATH 67"


def test_pilot_provider_collects_multiple_section_pages() -> None:
    source = get_college_source(2)
    session = _FakeSession(
        get_responses=[
            _FakeResponse(
                text="bootstrap",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/Search",
            )
        ],
        post_responses=[
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={
                    "Sections": [
                        {
                            "Synonym": "10001",
                            "AvailabilityStatusDisplay": "Open",
                            "InstructionalMethodsDisplay": "Online, Asynchronous",
                            "Title": "Course A",
                            "FacultyDisplay": ["One"],
                        }
                    ],
                    "TotalPages": 2,
                },
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={
                    "Sections": [
                        {
                            "Synonym": "10002",
                            "AvailabilityStatusDisplay": "Closed",
                            "InstructionalMethodsDisplay": ["Lecture"],
                            "Title": "Course A",
                            "FacultyDisplay": ["Two"],
                        }
                    ],
                    "TotalPages": 2,
                },
            ),
        ],
    )
    provider = EvergreenBannerProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 1B"
    )

    assert out.offered is True
    assert len(out.sections) == 2
    assert out.sections[0].modality == "online"
    assert session.calls[1][1]["pageNumber"] == "1"
    assert session.calls[2][1]["pageNumber"] == "2"


def test_pilot_provider_handles_missing_course() -> None:
    source = get_college_source(2)
    session = _FakeSession(
        get_responses=[
            _FakeResponse(
                text="bootstrap",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/Search",
            )
        ],
        post_responses=[
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={"Sections": []},
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={"CourseFullModels": []},
            ),
        ],
    )
    provider = EvergreenBannerProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="BIOLOGY"
    )
    assert out.offered is False
    assert out.sections == []
