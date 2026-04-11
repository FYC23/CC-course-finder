from __future__ import annotations

import re
from urllib.parse import urlsplit

import requests

from .models import CollegeScheduleSource, CourseAvailability, ParsedSection
from .term import ParsedTerm

_STATUS_MAP = {
    "open": "open",
    "open seats": "open",
    "closed": "closed",
    "full": "closed",
}

_COURSE_CODE_RE = re.compile(r"^\s*([A-Za-z]+)\s*[- ]?\s*([0-9]+[A-Za-z]?)\s*$")
_NUM_SUFFIX_RE = re.compile(r"^([0-9]+)([A-Za-z]?)$")
_PAGE_SIZE = 100


class EvergreenBannerProvider:
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def search_course(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, course_code: str
    ) -> CourseAvailability:
        term_code = _term_to_banner_code(term)
        base_root = _base_root_from_url(source.base_url)
        bootstrap_url = f"{base_root}/Student/Courses/Search"
        search_url = f"{base_root}/Student/Courses/PostSearchCriteria"
        sections_url = f"{base_root}/Student/Courses/Sections"

        last_response: requests.Response | None = None
        for keyword in _keyword_variants(course_code):
            bootstrap = self._session.get(
                bootstrap_url,
                params={
                    "keyword": keyword,
                    "Terms": term_code,
                    "locations": "EVC",
                },
                timeout=20,
            )
            bootstrap.raise_for_status()

            section_listing, sections = _search_section_listing(
                session=self._session,
                search_url=search_url,
                keyword=keyword,
                term_code=term_code,
            )
            last_response = section_listing
            if sections:
                return _build_availability(
                    source=source,
                    term=term,
                    course_code=course_code,
                    sections=sections,
                    source_url=section_listing.url,
                    raw_summary=section_listing.text,
                )

            catalog_listing = self._session.post(
                search_url,
                json=_build_search_payload(
                    keyword=keyword,
                    term_code=term_code,
                    view="CatalogListing",
                ),
                timeout=20,
            )
            catalog_listing.raise_for_status()
            last_response = catalog_listing
            sections = _fetch_sections_from_catalog(
                session=self._session,
                sections_url=sections_url,
                payload=_safe_json(catalog_listing),
            )
            if sections:
                return _build_availability(
                    source=source,
                    term=term,
                    course_code=course_code,
                    sections=sections,
                    source_url=catalog_listing.url,
                    raw_summary=catalog_listing.text,
                )

        return _build_availability(
            source=source,
            term=term,
            course_code=course_code,
            sections=[],
            source_url=source.base_url if last_response is None else last_response.url,
            raw_summary="" if last_response is None else last_response.text,
        )


def _build_search_payload(
    *, keyword: str, term_code: str, view: str, page_number: int = 1
) -> dict[str, object]:
    return {
        "keyword": keyword,
        "pageNumber": page_number,
        "quantityPerPage": _PAGE_SIZE,
        "searchResultsView": view,
        "terms": [term_code],
        "locations": ["EVC"],
    }


def _base_root_from_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "https://colss-prod.ec.sjeccd.edu"


def _safe_json(response: requests.Response) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError as err:
        raise requests.RequestException(
            f"Ellucian response was not valid JSON at {response.url}"
        ) from err
    if not isinstance(payload, dict):
        raise requests.RequestException(
            f"Ellucian response JSON root must be object at {response.url}"
        )
    return payload


def _term_to_banner_code(term: ParsedTerm) -> str:
    season_to_code = {"spring": "SP", "summer": "SU", "fall": "FA"}
    season_code = season_to_code.get(term.season)
    if season_code is None:
        raise ValueError(f"Unsupported season for banner mapping: {term.season}")
    return f"{term.year}{season_code}"


def _search_section_listing(
    *,
    session: requests.Session,
    search_url: str,
    keyword: str,
    term_code: str,
) -> tuple[requests.Response, list[ParsedSection]]:
    page_number = 1
    all_sections: list[ParsedSection] = []
    last_response: requests.Response | None = None
    while True:
        response = session.post(
            search_url,
            json=_build_search_payload(
                keyword=keyword,
                term_code=term_code,
                view="SectionListing",
                page_number=page_number,
            ),
            timeout=20,
        )
        response.raise_for_status()
        last_response = response
        payload = _safe_json(response)
        all_sections.extend(_parse_section_listing(payload))

        total_pages_raw = payload.get("TotalPages")
        total_pages = int(total_pages_raw) if isinstance(total_pages_raw, int) else 1
        if page_number >= total_pages:
            break
        page_number += 1

    if last_response is None:
        raise requests.RequestException("Section listing request produced no response")
    return last_response, all_sections


def _parse_section_listing(payload: dict[str, object]) -> list[ParsedSection]:
    sections: list[ParsedSection] = []
    for raw_section in payload.get("Sections", []):
        if not isinstance(raw_section, dict):
            continue
        section = _parse_section(raw_section, wrapper=None)
        if section is not None:
            sections.append(section)
    return sections


def _fetch_sections_from_catalog(
    *, session: requests.Session, sections_url: str, payload: dict[str, object]
) -> list[ParsedSection]:
    sections: list[ParsedSection] = []
    seen_ids: set[str] = set()
    for course in payload.get("CourseFullModels", []):
        if not isinstance(course, dict):
            continue
        course_id = course.get("Id")
        section_ids = course.get("MatchingSectionIds")
        if not course_id or not isinstance(section_ids, list) or not section_ids:
            continue
        section_response = session.post(
            sections_url,
            json={"courseId": course_id, "sectionIds": section_ids},
            timeout=20,
        )
        section_response.raise_for_status()
        for section in _parse_sections_response(_safe_json(section_response)):
            if section.section_id in seen_ids:
                continue
            seen_ids.add(section.section_id)
            sections.append(section)
    return sections


def _parse_sections_response(payload: dict[str, object]) -> list[ParsedSection]:
    sections_retrieved = payload.get("SectionsRetrieved")
    if not isinstance(sections_retrieved, dict):
        return []
    out: list[ParsedSection] = []
    for term_entry in sections_retrieved.get("TermsAndSections", []):
        if not isinstance(term_entry, dict):
            continue
        for wrapped in term_entry.get("Sections", []):
            if not isinstance(wrapped, dict):
                continue
            section_body = wrapped.get("Section")
            if not isinstance(section_body, dict):
                continue
            section = _parse_section(section_body, wrapper=wrapped)
            if section is not None:
                out.append(section)
    return out


def _parse_section(
    body: dict[str, object], wrapper: dict[str, object] | None
) -> ParsedSection | None:
    section_id = _first_str(body.get("Synonym"), body.get("Number"), body.get("Id"))
    if section_id is None:
        return None

    status = _normalize_status(
        _first_str(body.get("AvailabilityStatusDisplay"), body.get("AvailabilityStatus"))
    )
    modality = _normalize_modality(
        instructional_methods=body.get("InstructionalMethodsDisplay"),
        meetings=body.get("Meetings"),
    )
    title = _first_str(body.get("Title"), body.get("SectionTitleDisplay"), body.get("CourseName")) or ""
    instructor = _normalize_instructor(wrapper=wrapper, body=body)

    return ParsedSection(
        section_id=section_id,
        status=status,
        modality=modality,
        title=title,
        instructor=instructor,
    )


def _normalize_status(raw_status: str | None) -> str:
    if raw_status is None:
        return "unknown"
    return _STATUS_MAP.get(raw_status.strip().lower(), "unknown")


def _normalize_modality(*, instructional_methods: object, meetings: object) -> str:
    methods: list[str] = []
    if isinstance(instructional_methods, list):
        methods = [str(method).lower() for method in instructional_methods]
    elif isinstance(instructional_methods, str):
        methods = [instructional_methods.lower()]

    methods_text = " ".join(methods)
    if methods_text:
        if "hybrid" in methods_text:
            return "hybrid"
        if "online" in methods_text or "asynchronous" in methods_text or "synchronous" in methods_text:
            return "online"

    if isinstance(meetings, list):
        has_online = False
        has_in_person = False
        for meeting in meetings:
            if not isinstance(meeting, dict):
                continue
            if meeting.get("IsOnline") is True:
                has_online = True
            if meeting.get("IsOnline") is False:
                has_in_person = True
        if has_online and has_in_person:
            return "hybrid"
        if has_online:
            return "online"
        if has_in_person:
            return "in_person"

    if methods_text:
        return "in_person"
    return "unknown"


def _normalize_instructor(*, wrapper: dict[str, object] | None, body: dict[str, object]) -> str:
    for source in (wrapper or {}, body):
        faculty = source.get("FacultyDisplay")
        if isinstance(faculty, list):
            names = [str(name).strip() for name in faculty if str(name).strip()]
            if names:
                return ", ".join(names)
        if isinstance(faculty, str) and faculty.strip():
            return faculty.strip()
    return ""


def _first_str(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int):
            return str(value)
    return None


def _keyword_variants(course_code: str) -> list[str]:
    cleaned = course_code.strip()
    if not cleaned:
        return [course_code]

    out: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        candidate = value.strip()
        if not candidate or candidate in seen:
            return
        seen.add(candidate)
        out.append(candidate)

    add(cleaned)

    match = _COURSE_CODE_RE.match(cleaned)
    if not match:
        return out
    department = match.group(1).upper()
    token = match.group(2).upper()
    num_match = _NUM_SUFFIX_RE.match(token)
    if not num_match:
        return out
    digits, suffix = num_match.groups()
    stripped_digits = digits.lstrip("0") or "0"
    stripped_token = f"{stripped_digits}{suffix}"

    add(f"{department} {stripped_token}")
    add(f"{department}-{stripped_token}")

    if digits == stripped_digits and len(digits) < 3:
        padded_digits = digits.zfill(3)
        padded_token = f"{padded_digits}{suffix}"
        add(f"{department} {padded_token}")
        add(f"{department}-{padded_token}")

    return out


def _build_availability(
    *,
    source: CollegeScheduleSource,
    term: ParsedTerm,
    course_code: str,
    sections: list[ParsedSection],
    source_url: str,
    raw_summary: str,
) -> CourseAvailability:
    return CourseAvailability(
        cc_id=source.cc_id,
        cc_name=source.cc_name,
        term=term.label,
        course_code=course_code,
        offered=bool(sections),
        sections=sections,
        source_url=source_url,
        raw_summary=raw_summary[:500],
    )
