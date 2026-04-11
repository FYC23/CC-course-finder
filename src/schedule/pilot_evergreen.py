from __future__ import annotations

import re
from dataclasses import dataclass
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
_GENERAL_COURSE_CODE_RE = re.compile(r"^\s*([A-Za-z]+)\s*[- ]?\s*([A-Za-z0-9]+)\s*$")
_MATCH_STATS_SUFFIX_RE = re.compile(
    r"\[match_filter matched=\d+ unknown=\d+ dropped_nonmatch=\d+\]$"
)
_PAGE_SIZE = 100
_RAW_SUMMARY_LIMIT = 500


@dataclass
class _MatchStats:
    matched: int = 0
    unknown: int = 0
    dropped_nonmatch: int = 0

    def absorb(self, other: _MatchStats) -> None:
        self.matched += other.matched
        self.unknown += other.unknown
        self.dropped_nonmatch += other.dropped_nonmatch


class EvergreenBannerProvider:
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def search_course(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, course_code: str
    ) -> CourseAvailability:
        term_code = _term_to_banner_code(term)
        requested_identity = _parse_requested_course_identity(course_code)
        base_root = _base_root_from_url(source.base_url)
        bootstrap_url = f"{base_root}/Student/Courses/Search"
        search_url = f"{base_root}/Student/Courses/PostSearchCriteria"
        sections_url = f"{base_root}/Student/Courses/Sections"

        last_response: requests.Response | None = None
        last_stats = _MatchStats()
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

            section_listing, sections, section_stats = _search_section_listing(
                session=self._session,
                search_url=search_url,
                keyword=keyword,
                term_code=term_code,
                requested_identity=requested_identity,
            )
            last_response = section_listing
            last_stats = section_stats
            if sections:
                return _build_availability(
                    source=source,
                    term=term,
                    course_code=course_code,
                    sections=sections,
                    source_url=section_listing.url,
                    raw_summary=_append_match_stats(section_listing.text, section_stats),
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
            sections, catalog_stats = _fetch_sections_from_catalog(
                session=self._session,
                sections_url=sections_url,
                payload=_safe_json(catalog_listing),
                requested_identity=requested_identity,
            )
            stats = _MatchStats()
            stats.absorb(section_stats)
            stats.absorb(catalog_stats)
            last_stats = stats
            if sections:
                return _build_availability(
                    source=source,
                    term=term,
                    course_code=course_code,
                    sections=sections,
                    source_url=catalog_listing.url,
                    raw_summary=_append_match_stats(catalog_listing.text, stats),
                )

        return _build_availability(
            source=source,
            term=term,
            course_code=course_code,
            sections=[],
            source_url=source.base_url if last_response is None else last_response.url,
            raw_summary=_append_match_stats(
                "" if last_response is None else last_response.text, last_stats
            ),
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
    requested_identity: tuple[str, str] | None,
) -> tuple[requests.Response, list[ParsedSection], _MatchStats]:
    page_number = 1
    all_sections: list[ParsedSection] = []
    all_stats = _MatchStats()
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
        parsed_sections, stats = _parse_section_listing(
            payload=payload, requested_identity=requested_identity
        )
        all_sections.extend(parsed_sections)
        all_stats.absorb(stats)

        total_pages_raw = payload.get("TotalPages")
        total_pages = int(total_pages_raw) if isinstance(total_pages_raw, int) else 1
        if page_number >= total_pages:
            break
        page_number += 1

    if last_response is None:
        raise requests.RequestException("Section listing request produced no response")
    all_stats.matched = len(all_sections)
    return last_response, all_sections, all_stats


def _parse_section_listing(
    *, payload: dict[str, object], requested_identity: tuple[str, str] | None
) -> tuple[list[ParsedSection], _MatchStats]:
    sections: list[ParsedSection] = []
    stats = _MatchStats()
    for raw_section in payload.get("Sections", []):
        if not isinstance(raw_section, dict):
            continue
        match_status = _classify_catalog_match(
            raw_row=raw_section, requested_identity=requested_identity
        )
        if match_status == "unknown":
            stats.unknown += 1
            continue
        if match_status == "nonmatch":
            stats.dropped_nonmatch += 1
            continue
        section = _parse_section(raw_section, wrapper=None)
        if section is not None:
            sections.append(section)
    stats.matched = len(sections)
    return sections, stats


def _fetch_sections_from_catalog(
    *,
    session: requests.Session,
    sections_url: str,
    payload: dict[str, object],
    requested_identity: tuple[str, str] | None,
) -> tuple[list[ParsedSection], _MatchStats]:
    sections: list[ParsedSection] = []
    seen_ids: set[str] = set()
    stats = _MatchStats()
    for course in payload.get("CourseFullModels", []):
        if not isinstance(course, dict):
            continue
        course_id = course.get("Id")
        section_ids = course.get("MatchingSectionIds")
        if not course_id or not isinstance(section_ids, list) or not section_ids:
            continue

        course_match = _classify_catalog_match(
            raw_row=course, requested_identity=requested_identity
        )
        if course_match == "nonmatch":
            stats.dropped_nonmatch += len(section_ids)
            continue

        fallback_identity = _extract_catalog_identity(course)
        section_response = session.post(
            sections_url,
            json={"courseId": course_id, "sectionIds": section_ids},
            timeout=20,
        )
        section_response.raise_for_status()
        parsed_sections, parse_stats = _parse_sections_response(
            payload=_safe_json(section_response),
            requested_identity=requested_identity,
            fallback_identity=fallback_identity if course_match == "matched" else None,
        )
        stats.absorb(parse_stats)
        for section in parsed_sections:
            if section.section_id in seen_ids:
                continue
            seen_ids.add(section.section_id)
            sections.append(section)
    stats.matched = len(sections)
    return sections, stats


def _parse_sections_response(
    *,
    payload: dict[str, object],
    requested_identity: tuple[str, str] | None,
    fallback_identity: tuple[str, str] | None = None,
) -> tuple[list[ParsedSection], _MatchStats]:
    sections_retrieved = payload.get("SectionsRetrieved")
    if not isinstance(sections_retrieved, dict):
        return [], _MatchStats()
    out: list[ParsedSection] = []
    stats = _MatchStats()
    for term_entry in sections_retrieved.get("TermsAndSections", []):
        if not isinstance(term_entry, dict):
            continue
        for wrapped in term_entry.get("Sections", []):
            if not isinstance(wrapped, dict):
                continue
            section_body = wrapped.get("Section")
            if not isinstance(section_body, dict):
                continue
            section_match = _classify_catalog_match(
                raw_row=section_body,
                requested_identity=requested_identity,
                fallback_identity=fallback_identity,
            )
            if section_match == "nonmatch":
                stats.dropped_nonmatch += 1
                continue
            if section_match == "unknown":
                stats.unknown += 1
                continue
            section = _parse_section(section_body, wrapper=wrapped)
            if section is not None:
                out.append(section)
    stats.matched = len(out)
    return out, stats


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


def _append_match_stats(raw_summary: str, stats: _MatchStats) -> str:
    suffix = (
        f"[match_filter matched={stats.matched} "
        f"unknown={stats.unknown} dropped_nonmatch={stats.dropped_nonmatch}]"
    )
    if raw_summary:
        return f"{raw_summary}\n{suffix}"
    return suffix


def _parse_requested_course_identity(course_code: str) -> tuple[str, str] | None:
    return _parse_course_identity_text(course_code)


def _classify_catalog_match(
    *,
    raw_row: dict[str, object],
    requested_identity: tuple[str, str] | None,
    fallback_identity: tuple[str, str] | None = None,
) -> str:
    if requested_identity is None:
        return "matched"

    candidate = _extract_catalog_identity(raw_row)
    if candidate is None:
        candidate = fallback_identity
    if candidate is None:
        return "unknown"
    if _course_identities_match(requested_identity, candidate):
        return "matched"
    return "nonmatch"


def _extract_catalog_identity(raw_row: dict[str, object]) -> tuple[str, str] | None:
    course_obj = raw_row.get("Course")
    if isinstance(course_obj, dict):
        subject = _first_str(
            course_obj.get("SubjectCode"),
            course_obj.get("Subject"),
            course_obj.get("SubjectDisplay"),
        )
        number = _first_str(
            course_obj.get("Number"),
            course_obj.get("CourseNumber"),
            course_obj.get("NumberDisplay"),
        )
        identity = _normalize_identity(subject=subject, number=number)
        if identity is not None:
            return identity

    course_name = _first_str(raw_row.get("CourseName"))
    if course_name is None:
        return None
    return _parse_course_identity_text(course_name)


def _parse_course_identity_text(text: str) -> tuple[str, str] | None:
    match = _GENERAL_COURSE_CODE_RE.match(text.strip())
    if not match:
        return None
    return _normalize_identity(subject=match.group(1), number=match.group(2))


def _normalize_identity(*, subject: str | None, number: str | None) -> tuple[str, str] | None:
    if not subject or not number:
        return None
    normalized_subject = re.sub(r"[^A-Za-z]", "", subject).upper()
    normalized_number = re.sub(r"[^0-9A-Za-z]", "", number).upper()
    if not normalized_subject or not normalized_number:
        return None
    return normalized_subject, normalized_number


def _course_identities_match(
    requested_identity: tuple[str, str], candidate_identity: tuple[str, str]
) -> bool:
    req_subject, req_number = requested_identity
    cand_subject, cand_number = candidate_identity
    if req_subject != cand_subject:
        return False
    return _normalize_number_token(req_number) == _normalize_number_token(cand_number)


def _normalize_number_token(number: str) -> str:
    match = _NUM_SUFFIX_RE.match(number.upper())
    if match is None:
        return number.upper()
    digits, suffix = match.groups()
    return f"{digits.lstrip('0') or '0'}{suffix}"


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
        raw_summary=_truncate_raw_summary(raw_summary),
    )


def _truncate_raw_summary(raw_summary: str) -> str:
    if len(raw_summary) <= _RAW_SUMMARY_LIMIT:
        return raw_summary

    lines = raw_summary.rstrip().splitlines()
    suffix = ""
    if lines and _MATCH_STATS_SUFFIX_RE.fullmatch(lines[-1]):
        suffix = lines[-1]
    if not suffix:
        return raw_summary[:_RAW_SUMMARY_LIMIT]

    budget = _RAW_SUMMARY_LIMIT - len(suffix) - 1
    if budget <= 0:
        return suffix[-_RAW_SUMMARY_LIMIT:]
    base = raw_summary[:budget]
    return f"{base}\n{suffix}"
