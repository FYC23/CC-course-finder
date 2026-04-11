from __future__ import annotations

import json

from src.schedule.catalog import get_college_source
from src.schedule.banner_ellucian import BannerEllucianProvider
from src.schedule.models import CollegeScheduleSource
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
                "CourseName": "MATH-1B",
                "FacultyDisplay": ["Ada Lovelace"],
            },
            {
                "Synonym": "12346",
                "Number": "202",
                "AvailabilityStatusDisplay": "Closed",
                "InstructionalMethodsDisplay": ["Lecture"],
                "Title": "Calculus II",
                "CourseName": "MATH-1B",
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
    provider = BannerEllucianProvider(session=session)

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
        "CourseFullModels": [
            {
                "Id": "course-1",
                "MatchingSectionIds": ["sec-1"],
                "Course": {"SubjectCode": "MATH", "Number": "067"},
            }
        ]
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
    provider = BannerEllucianProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 067"
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
                            "CourseName": "MATH-067",
                            "FacultyDisplay": ["Ada"],
                        }
                    ]
                },
            ),
        ],
    )
    provider = BannerEllucianProvider(session=session)

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
                            "CourseName": "MATH-1B",
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
                            "CourseName": "MATH-1B",
                            "FacultyDisplay": ["Two"],
                        }
                    ],
                    "TotalPages": 2,
                },
            ),
        ],
    )
    provider = BannerEllucianProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 1B"
    )

    assert out.offered is True
    assert len(out.sections) == 2
    assert out.sections[0].modality == "online"
    assert session.calls[1][1]["pageNumber"] == "1"
    assert session.calls[2][1]["pageNumber"] == "2"


def test_pilot_provider_accepts_string_total_pages() -> None:
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
                    "Sections": [],
                    "TotalPages": "2",
                },
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={
                    "Sections": [
                        {
                            "Synonym": "10003",
                            "AvailabilityStatusDisplay": "Open",
                            "InstructionalMethodsDisplay": ["Online"],
                            "Title": "Course B",
                            "CourseName": "MATH-1B",
                        }
                    ],
                    "TotalPages": "2",
                },
            ),
        ],
    )
    provider = BannerEllucianProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 1B"
    )

    assert out.offered is True
    section_calls = [
        call for call in session.calls if call[1].get("searchResultsView") == "SectionListing"
    ]
    assert len(section_calls) == 2


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
    provider = BannerEllucianProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="BIOLOGY!"
    )
    assert out.offered is False
    assert out.sections == []


def test_pilot_provider_filters_non_matching_section_listing_rows() -> None:
    source = get_college_source(2)
    payload = {
        "Sections": [
            {
                "Synonym": "20001",
                "AvailabilityStatusDisplay": "Open",
                "InstructionalMethodsDisplay": ["Online"],
                "Title": "Math for Stats",
                "CourseName": "MATH-067",
            },
            {
                "Synonym": "20002",
                "AvailabilityStatusDisplay": "Open",
                "InstructionalMethodsDisplay": ["Online"],
                "Title": "Intro Stats",
                "CourseName": "STAT-C1000",
            },
        ]
    }
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
                json_obj=payload,
            )
        ],
    )
    provider = BannerEllucianProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 067"
    )

    assert out.offered is True
    assert [section.section_id for section in out.sections] == ["20001"]
    assert "dropped_nonmatch=1" in out.raw_summary


def test_pilot_provider_marks_unknown_identity_rows_in_summary() -> None:
    source = get_college_source(2)
    payload = {
        "Sections": [
            {
                "Synonym": "30001",
                "AvailabilityStatusDisplay": "Open",
                "InstructionalMethodsDisplay": ["Online"],
                "Title": "Unknown Math Section",
            }
        ]
    }
    session = _FakeSession(
        get_responses=[
            _FakeResponse(
                text="bootstrap",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/Search",
            ),
            _FakeResponse(
                text="bootstrap",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/Search",
            ),
            _FakeResponse(
                text="bootstrap",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/Search",
            ),
        ],
        post_responses=[
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj=payload,
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={"CourseFullModels": []},
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj=payload,
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={"CourseFullModels": []},
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj=payload,
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={"CourseFullModels": []},
            ),
        ],
    )
    provider = BannerEllucianProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 067"
    )

    assert out.offered is False
    assert out.sections == []
    assert "unknown=1" in out.raw_summary


def test_pilot_provider_prefers_course_object_over_course_name() -> None:
    source = get_college_source(2)
    payload = {
        "Sections": [
            {
                "Synonym": "40001",
                "AvailabilityStatusDisplay": "Open",
                "InstructionalMethodsDisplay": ["Online"],
                "Title": "Math Section",
                "CourseName": "STAT-C1000",
                "Course": {"SubjectCode": "MATH", "Number": "067"},
            }
        ]
    }
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
                json_obj=payload,
            )
        ],
    )
    provider = BannerEllucianProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 067"
    )

    assert out.offered is True
    assert [section.section_id for section in out.sections] == ["40001"]


def test_pilot_provider_keeps_match_stats_when_raw_summary_is_long() -> None:
    source = get_college_source(2)
    payload = {
        "Sections": [
            {
                "Synonym": "50001",
                "AvailabilityStatusDisplay": "Open",
                "InstructionalMethodsDisplay": ["Online"],
                "CourseName": "MATH-067",
            }
        ]
    }
    session = _FakeSession(
        get_responses=[
            _FakeResponse(
                text="bootstrap",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/Search",
            )
        ],
        post_responses=[
            _FakeResponse(
                text="x" * 700,
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj=payload,
            )
        ],
    )
    provider = BannerEllucianProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 067"
    )

    assert out.offered is True
    assert out.raw_summary == "[match_filter matched=1 unknown=0 dropped_nonmatch=0]"


def test_pilot_provider_uses_wvc_location_token() -> None:
    source = get_college_source(80)
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
                            "Synonym": "60001",
                            "AvailabilityStatusDisplay": "Open",
                            "InstructionalMethodsDisplay": ["Online"],
                            "CourseName": "MATH-1B",
                        }
                    ]
                },
            )
        ],
    )
    provider = BannerEllucianProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 1B"
    )

    assert out.offered is True
    assert session.calls[0][1]["locations"] == "WVC"
    assert "WVC" in session.calls[1][1]["locations"]


def test_pilot_provider_rejects_unsupported_source_system() -> None:
    source = CollegeScheduleSource(
        cc_id=999,
        cc_name="Unsupported College",
        system="peoplesoft",
        base_url="https://example.edu",
        locations=("MAIN",),
    )
    provider = BannerEllucianProvider()

    try:
        provider.search_course(
            source=source, term=parse_term_label("Summer 2026"), course_code="MATH 1B"
        )
        raise AssertionError("expected ValueError for unsupported source")
    except ValueError as err:
        assert "does not support source system='peoplesoft'" in str(err)


def test_pilot_provider_caps_section_listing_pages() -> None:
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
                    "Sections": [],
                    "TotalPages": 10,
                },
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={"Sections": [], "TotalPages": 10},
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={"Sections": [], "TotalPages": 10},
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={"Sections": [], "TotalPages": 10},
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={"CourseFullModels": []},
            ),
        ],
    )
    provider = BannerEllucianProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="BIOLOGY!"
    )

    assert out.offered is False
    page_calls = [
        call
        for call in session.calls
        if call[1].get("searchResultsView") == "SectionListing"
    ]
    assert len(page_calls) == 4


def test_pilot_provider_caps_catalog_section_calls() -> None:
    source = get_college_source(2)
    catalog_rows = [
        {
            "Id": f"course-{idx}",
            "MatchingSectionIds": [f"sec-{idx}"],
            "Course": {"SubjectCode": "MATH", "Number": "067"},
        }
        for idx in range(20)
    ]
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
                json_obj={"CourseFullModels": catalog_rows},
            ),
            *[
                _FakeResponse(
                    text="",
                    url="https://colss-prod.ec.sjeccd.edu/Student/Courses/Sections",
                    json_obj={"SectionsRetrieved": {"TermsAndSections": []}},
                )
                for _ in range(12)
            ],
        ],
    )
    provider = BannerEllucianProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="BIOLOGY!"
    )

    assert out.offered is False
    section_calls = [
        call for call in session.calls if call[0].endswith("/Student/Courses/Sections")
    ]
    assert len(section_calls) == 12
