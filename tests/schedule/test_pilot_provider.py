from __future__ import annotations

import json

from src.schedule.catalog import get_college_source
from src.schedule.colleague_selfservice import ColleagueSelfServiceProvider
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
        self.headers: dict[str, str] = {}

    def get(self, url: str, params: dict[str, str], timeout: int) -> _FakeResponse:
        self.calls.append((url, params))
        return self._get_responses.pop(0)

    def post(
        self,
        url: str,
        json: dict[str, object],
        timeout: int,
        headers: dict[str, str] | None = None,
    ) -> _FakeResponse:
        params = {k: str(v) for k, v in json.items()}
        self.calls.append((url, params))
        return self._post_responses.pop(0)


def _term_filters_response(*, term_label: str = "Summer 2026", value: str = "2026SU") -> _FakeResponse:
    """The CatalogListing/TermFilters response the adapter's term-resolution POST expects.

    Consumed once (and cached per provider instance) before the keyword loop, since none of
    the sources exercised in this file set `params.term_format`.
    """
    return _FakeResponse(
        text="",
        url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
        json_obj={"TermFilters": [{"Value": value, "Description": term_label}]},
    )


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
            _term_filters_response(),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj=section_listing_payload,
            )
        ],
    )
    provider = ColleagueSelfServiceProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 1B"
    )

    assert out.offered is True
    assert len(out.sections) == 2
    # Delegating to colleague_sections.parse_section now runs the shared normalize.py
    # modality classifier (Task 1), which has no plain "online" value -- "Online,
    # Asynchronous" with no timed meeting evidence classifies as "async_online".
    assert out.sections[0].modality == "async_online"
    assert out.sections[1].status == "closed"
    # calls[0] is the bootstrap GET; it no longer carries a "Terms" param (the brief moves
    # term-code resolution to a separate POST against TermFilters), so that assertion is dropped.
    assert session.calls[0][1]["locations"] == "EVC"
    assert session.calls[0][1]["keyword"] == "MATH 1B"
    # calls[1] is the term-resolution POST (CatalogListing/TermFilters, no term_format set on
    # this source's params).
    assert session.calls[1][1]["searchResultsView"] == "CatalogListing"
    # calls[2] is the section listing POST, and it must carry the term code resolved from
    # TermFilters ("2026SU") rather than a hardcoded/derived one.
    assert session.calls[2][1]["searchResultsView"] == "SectionListing"
    assert session.calls[2][1]["terms"] == str(["2026SU"])


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
            _term_filters_response(),
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
    provider = ColleagueSelfServiceProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 067"
    )
    assert out.offered is True
    assert out.sections[0].section_id == "77777"
    assert out.sections[0].modality == "hybrid"
    assert out.sections[0].instructor == "Grace Hopper"
    # calls[1] is now the term-resolution POST, so the catalog-listing POST shifted from
    # calls[2] to calls[3].
    assert session.calls[3][1]["searchResultsView"] == "CatalogListing"


def test_pilot_provider_tries_keyword_variants_until_match() -> None:
    source = get_college_source(2)
    session = _FakeSession(
        get_responses=[
            _FakeResponse(
                text="bootstrap",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/Search",
            ),
        ],
        post_responses=[
            _term_filters_response(),
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
    provider = ColleagueSelfServiceProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 067"
    )

    assert out.offered is True
    assert out.sections[0].section_id == "90001"
    assert session.calls[0][1]["keyword"] == "MATH 067"
    # Bootstrap now happens once (not per keyword variant), so the second variant's keyword
    # shows up on its SectionListing POST (calls[4]) rather than on a second bootstrap GET.
    assert session.calls[4][1]["keyword"] == "MATH 67"


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
            _term_filters_response(),
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
    provider = ColleagueSelfServiceProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 1B"
    )

    assert out.offered is True
    assert len(out.sections) == 2
    # Same shared-normalizer change as above: "Online, Asynchronous" with no timed
    # meeting evidence classifies as "async_online", not the old local "online".
    assert out.sections[0].modality == "async_online"
    # calls[1] is the term-resolution POST; the two SectionListing pages shifted to
    # calls[2] and calls[3].
    assert session.calls[2][1]["pageNumber"] == "1"
    assert session.calls[3][1]["pageNumber"] == "2"


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
            _term_filters_response(),
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
    provider = ColleagueSelfServiceProvider(session=session)

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
            _term_filters_response(),
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
    provider = ColleagueSelfServiceProvider(session=session)

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
            _term_filters_response(),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj=payload,
            )
        ],
    )
    provider = ColleagueSelfServiceProvider(session=session)

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
        ],
        post_responses=[
            _term_filters_response(),
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
    provider = ColleagueSelfServiceProvider(session=session)

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
            _term_filters_response(),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj=payload,
            )
        ],
    )
    provider = ColleagueSelfServiceProvider(session=session)

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
            _term_filters_response(),
            _FakeResponse(
                text="x" * 700,
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj=payload,
            )
        ],
    )
    provider = ColleagueSelfServiceProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 067"
    )

    assert out.offered is True
    assert out.raw_summary == "[match_filter matched=1 unknown=0 dropped_nonmatch=0]"


def test_banner_provider_passes_location_token_to_requests() -> None:
    """Banner-only: synthetic COLSS source with a location token (not production WVC catalog)."""
    source = CollegeScheduleSource(
        cc_id=80,
        cc_name="West Valley College",
        system="colleague_selfservice",
        base_url="https://colss-prod.ncscsaas.elluciancloud.com/Student/Courses/SearchResult",
        locations=("WVC",),
    )
    session = _FakeSession(
        get_responses=[
            _FakeResponse(
                text="bootstrap",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/Search",
            )
        ],
        post_responses=[
            _term_filters_response(),
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
    provider = ColleagueSelfServiceProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 1B"
    )

    assert out.offered is True
    assert session.calls[0][1]["locations"] == "WVC"
    # calls[1] is the term-resolution POST (which always sends empty locations); the actual
    # SectionListing POST carrying the location filter shifted to calls[2].
    assert "WVC" in session.calls[2][1]["locations"]


def test_pilot_provider_handles_null_sections_and_null_course_full_models() -> None:
    """ASP.NET serializes an empty collection as JSON null, not []. Both
    "Sections": null (SectionListing) and "CourseFullModels": null (CatalogListing)
    must resolve to no results instead of crashing on `None` iteration."""
    source = get_college_source(2)
    session = _FakeSession(
        get_responses=[
            _FakeResponse(
                text="bootstrap",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/Search",
            )
        ],
        post_responses=[
            _term_filters_response(),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={"Sections": None},
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={"CourseFullModels": None},
            ),
        ],
    )
    provider = ColleagueSelfServiceProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="BIOLOGY!"
    )

    assert out.offered is False
    assert out.sections == []


def test_pilot_provider_handles_null_terms_and_sections_in_catalog_fallback() -> None:
    """The Sections endpoint response can also carry null for TermsAndSections, or for
    Sections within a term entry -- both must resolve to no sections, not a crash."""
    source = get_college_source(2)
    catalog_listing_payload = {
        "CourseFullModels": [
            {
                "Id": "course-1",
                "MatchingSectionIds": ["sec-1"],
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
            _term_filters_response(),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj={"Sections": None},
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/PostSearchCriteria",
                json_obj=catalog_listing_payload,
            ),
            _FakeResponse(
                text="",
                url="https://colss-prod.ec.sjeccd.edu/Student/Courses/Sections",
                json_obj={"SectionsRetrieved": {"TermsAndSections": None}},
            ),
        ],
    )
    provider = ColleagueSelfServiceProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="BIOLOGY!"
    )

    assert out.offered is False
    assert out.sections == []


def test_pilot_provider_rejects_unsupported_source_system() -> None:
    source = CollegeScheduleSource(
        cc_id=999,
        cc_name="Unsupported College",
        system="peoplesoft",
        base_url="https://example.edu",
        locations=("MAIN",),
    )
    provider = ColleagueSelfServiceProvider()

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
            _term_filters_response(),
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
    provider = ColleagueSelfServiceProvider(session=session)

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
            _term_filters_response(),
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
    provider = ColleagueSelfServiceProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="BIOLOGY!"
    )

    assert out.offered is False
    section_calls = [
        call for call in session.calls if call[0].endswith("/Student/Courses/Sections")
    ]
    assert len(section_calls) == 12
