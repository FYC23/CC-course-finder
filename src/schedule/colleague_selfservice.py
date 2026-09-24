from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

import requests

from .colleague_listing import fetch_subject_listing
from .colleague_sections import parse_section
from .listing import ListedCourse
from .models import CollegeScheduleSource, CourseAvailability, ParsedSection
from .term import ParsedTerm, TermNotListedError, term_match_rank

_COURSE_CODE_RE = re.compile(r"^\s*([A-Za-z]+)\s*[- ]?\s*([0-9]+[A-Za-z]?)\s*$")
_NUM_SUFFIX_RE = re.compile(r"^([0-9]+)([A-Za-z]?)$")
# The subject may be several words ("COMP SCI 1"); the lazy repeat keeps "CS V13" as CS + V13.
_GENERAL_COURSE_CODE_RE = re.compile(r"^\s*([A-Za-z]+(?:\s+[A-Za-z]+)*?)\s*[- ]?\s*([A-Za-z0-9]+)\s*$")
_PAGE_SIZE = 100
_MAX_KEYWORD_VARIANTS = 5
_MAX_SECTION_PAGES = 4
_MAX_CATALOG_SECTION_CALLS = 12
_DEBUG_RAW_SUMMARY = os.getenv("SCHEDULE_DEBUG_RAW_SUMMARY", "").strip() in {
    "1",
    "true",
    "yes",
}

_TOKEN_RE_NAME_FIRST = re.compile(
    r'name="__RequestVerificationToken"[^>]*?value="([^"]+)"', re.IGNORECASE
)
_TOKEN_RE_VALUE_FIRST = re.compile(
    r'value="([^"]+)"[^>]*?name="__RequestVerificationToken"', re.IGNORECASE
)
_SEASON2 = {"spring": "SP", "summer": "SU", "fall": "FA"}
_SEASON1 = {"spring": "S", "summer": "U", "fall": "F"}
_JSON_HEADERS = {"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"}


def extract_request_token(html: str) -> str | None:
    for pattern in (_TOKEN_RE_NAME_FIRST, _TOKEN_RE_VALUE_FIRST):
        match = pattern.search(html)
        if match:
            return match.group(1)
    return None


def format_term_code(term: ParsedTerm, fmt: str) -> str:
    return (
        fmt.replace("{yyyy}", str(term.year))
        .replace("{yy}", str(term.year)[-2:])
        .replace("{SEASON2}", _SEASON2[term.season])
        .replace("{SEASON1}", _SEASON1[term.season])
    )


def resolve_term_code(
    session: requests.Session,
    base_root: str,
    term: ParsedTerm,
    *,
    keyword: str,
    headers: dict[str, str],
) -> str:
    """Ask the portal for its term list (CatalogListing view) and match by label."""
    response = session.post(
        f"{base_root}/Student/Courses/PostSearchCriteria",
        json={
            "keyword": keyword,
            "pageNumber": 1,
            "quantityPerPage": 1,
            "searchResultsView": "CatalogListing",
            "terms": [],
            "locations": [],
        },
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()
    best: tuple[int, str] | None = None
    for entry in _safe_json(response).get("TermFilters") or []:
        if not isinstance(entry, dict) or not entry.get("Value"):
            continue
        description = str(entry.get("Description") or entry.get("Text") or "")
        rank = term_match_rank(term, description)
        if rank is None:
            continue
        if best is None or rank < best[0]:
            best = (rank, str(entry["Value"]))
    if best is not None:
        return best[1]
    raise TermNotListedError(
        f"Term {term.label!r} not found in Colleague TermFilters at {base_root}"
    )


@dataclass(frozen=True)
class _MatchStats:
    matched: int = 0
    unknown: int = 0
    dropped_nonmatch: int = 0

    def combined(self, other: _MatchStats) -> _MatchStats:
        return _MatchStats(
            matched=self.matched + other.matched,
            unknown=self.unknown + other.unknown,
            dropped_nonmatch=self.dropped_nonmatch + other.dropped_nonmatch,
        )


class ColleagueSelfServiceProvider:
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._term_cache: dict[tuple[str, str], str] = {}

    def supports_source(self, source: CollegeScheduleSource) -> bool:
        return source.system == "colleague_selfservice"

    def _bootstrap(
        self, bootstrap_url: str, *, course_code: str, locations: tuple[str, ...]
    ) -> dict[str, str]:
        """Fetch the portal's search page and build this college's request headers.

        The session (and this provider) is reused across every college in
        ScheduleService.query, so the anti-forgery token and JSON headers must never be
        written onto ``self._session.headers`` -- that would leak one college's token (or
        Content-Type) onto the next college's requests. Instead, return a fresh dict the
        caller threads through explicitly on every subsequent request for this college.
        """
        params: dict[str, str] = {"keyword": course_code}
        if locations:
            params["locations"] = locations[0]
        response = self._session.get(bootstrap_url, params=params, timeout=20)
        response.raise_for_status()
        token = extract_request_token(response.text)
        headers = dict(_JSON_HEADERS)
        if token:
            headers["__RequestVerificationToken"] = token
        return headers

    def _term_code(
        self,
        base_root: str,
        term: ParsedTerm,
        *,
        source: CollegeScheduleSource,
        headers: dict[str, str],
    ) -> str:
        fmt = source.params.get("term_format")
        if fmt:
            return format_term_code(term, fmt)
        cache_key = (base_root, term.label)
        if cache_key not in self._term_cache:
            # TermFilters are search facets that depend on the keyword (a real course can
            # omit some terms, and a nonsense keyword returns none at all), so resolving the
            # term list always uses an empty keyword to get the full, unfiltered list.
            self._term_cache[cache_key] = resolve_term_code(
                self._session, base_root, term, keyword="", headers=headers
            )
        return self._term_cache[cache_key]

    def search_course(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, course_code: str
    ) -> CourseAvailability:
        if not self.supports_source(source):
            raise ValueError(
                f"Provider ColleagueSelfServiceProvider does not support source system="
                f"{source.system!r} for cc_id={source.cc_id}"
            )

        requested_identity = _parse_requested_course_identity(course_code)
        base_root = _base_root_from_url(source.base_url)
        bootstrap_url = f"{base_root}/Student/Courses/Search"
        search_url = f"{base_root}/Student/Courses/PostSearchCriteria"
        sections_url = f"{base_root}/Student/Courses/Sections"
        locations = source.locations
        location_match = source.params.get("location_match", "").strip().lower()
        headers = self._bootstrap(bootstrap_url, course_code=course_code, locations=locations)
        term_code = self._term_code(base_root, term, source=source, headers=headers)

        last_response: requests.Response | None = None
        last_stats = _MatchStats()
        for keyword in _keyword_variants(course_code)[:_MAX_KEYWORD_VARIANTS]:
            section_listing, sections, section_stats = _search_section_listing(
                session=self._session,
                search_url=search_url,
                keyword=keyword,
                term_code=term_code,
                requested_identity=requested_identity,
                locations=locations,
                location_match=location_match,
                headers=headers,
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
                    raw_summary=_build_raw_summary(section_listing.text, section_stats),
                )

            catalog_listing = self._session.post(
                search_url,
                json=_build_search_payload(
                    keyword=keyword,
                    term_code=term_code,
                    view="CatalogListing",
                    locations=locations,
                ),
                headers=headers,
                timeout=20,
            )
            catalog_listing.raise_for_status()
            last_response = catalog_listing
            sections, catalog_stats = _fetch_sections_from_catalog(
                session=self._session,
                sections_url=sections_url,
                payload=_safe_json(catalog_listing),
                requested_identity=requested_identity,
                location_match=location_match,
                headers=headers,
            )
            stats = section_stats.combined(catalog_stats)
            last_stats = stats
            if sections:
                return _build_availability(
                    source=source,
                    term=term,
                    course_code=course_code,
                    sections=sections,
                    source_url=catalog_listing.url,
                    raw_summary=_build_raw_summary(catalog_listing.text, stats),
                )
            if _is_clear_miss(_safe_json(catalog_listing), requested_identity):
                break

        return _build_availability(
            source=source,
            term=term,
            course_code=course_code,
            sections=[],
            source_url=source.base_url if last_response is None else last_response.url,
            raw_summary=_build_raw_summary(
                "" if last_response is None else last_response.text, last_stats
            ),
        )

    def list_subject(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, subject: str
    ) -> tuple[ListedCourse, ...]:
        """Every course in ``subject`` this term, with catalog descriptions (discover pass only)."""
        base_root = _base_root_from_url(source.base_url)
        subject = subject.strip().upper()
        headers = self._bootstrap(
            f"{base_root}/Student/Courses/Search", course_code=subject, locations=source.locations
        )
        term_code = self._term_code(base_root, term, source=source, headers=headers)
        return fetch_subject_listing(
            self._session,
            search_url=f"{base_root}/Student/Courses/PostSearchCriteria",
            subject=subject,
            term_code=term_code,
            locations=source.locations,
            headers=headers,
        )


def _build_search_payload(
    *,
    keyword: str,
    term_code: str,
    view: str,
    locations: tuple[str, ...],
    page_number: int = 1,
) -> dict[str, object]:
    return {
        "keyword": keyword,
        "pageNumber": page_number,
        "quantityPerPage": _PAGE_SIZE,
        "searchResultsView": view,
        "terms": [term_code],
        "locations": list(locations),
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


def _location_ok(raw_row: dict[str, object], location_match: str) -> bool:
    if not location_match:
        return True
    haystack = " ".join(
        str(raw_row.get(key) or "") for key in ("LocationDisplay", "Location", "LocationCode")
    ).lower()
    return location_match in haystack


def _search_section_listing(
    *,
    session: requests.Session,
    search_url: str,
    keyword: str,
    term_code: str,
    requested_identity: tuple[str, str] | None,
    locations: tuple[str, ...],
    headers: dict[str, str],
    location_match: str = "",
) -> tuple[requests.Response, list[ParsedSection], _MatchStats]:
    page_number = 1
    all_sections: list[ParsedSection] = []
    combined_stats = _MatchStats()
    last_response: requests.Response | None = None
    while True:
        response = session.post(
            search_url,
            json=_build_search_payload(
                keyword=keyword,
                term_code=term_code,
                view="SectionListing",
                page_number=page_number,
                locations=locations,
            ),
            headers=headers,
            timeout=20,
        )
        response.raise_for_status()
        last_response = response
        payload = _safe_json(response)
        parsed_sections, stats = _parse_section_listing(
            payload=payload, requested_identity=requested_identity, location_match=location_match
        )
        all_sections.extend(parsed_sections)
        combined_stats = combined_stats.combined(stats)

        total_pages = _coerce_total_pages(payload.get("TotalPages"))
        if page_number >= total_pages or page_number >= _MAX_SECTION_PAGES:
            break
        page_number += 1

    if last_response is None:
        raise requests.RequestException("Section listing request produced no response")
    final_stats = replace(combined_stats, matched=len(all_sections))
    return last_response, all_sections, final_stats


def _parse_section_listing(
    *,
    payload: dict[str, object],
    requested_identity: tuple[str, str] | None,
    location_match: str = "",
) -> tuple[list[ParsedSection], _MatchStats]:
    sections: list[ParsedSection] = []
    unknown = 0
    dropped_nonmatch = 0
    for raw_section in payload.get("Sections") or []:
        if not isinstance(raw_section, dict):
            continue
        match_status = _classify_catalog_match(
            raw_row=raw_section, requested_identity=requested_identity
        )
        if match_status == "unknown":
            unknown += 1
            continue
        if match_status == "nonmatch":
            dropped_nonmatch += 1
            continue
        if not _location_ok(raw_section, location_match):
            dropped_nonmatch += 1
            continue
        section = parse_section(raw_section, wrapper=None)
        if section is not None:
            sections.append(section)
    return sections, _MatchStats(
        matched=len(sections), unknown=unknown, dropped_nonmatch=dropped_nonmatch
    )


def _fetch_sections_from_catalog(
    *,
    session: requests.Session,
    sections_url: str,
    payload: dict[str, object],
    requested_identity: tuple[str, str] | None,
    headers: dict[str, str],
    location_match: str = "",
) -> tuple[list[ParsedSection], _MatchStats]:
    sections: list[ParsedSection] = []
    seen_ids: set[str] = set()
    unknown = 0
    dropped_nonmatch = 0
    section_calls = 0
    for course in payload.get("CourseFullModels") or []:
        if section_calls >= _MAX_CATALOG_SECTION_CALLS:
            break
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
            dropped_nonmatch += len(section_ids)
            continue

        fallback_identity = _extract_catalog_identity(course)
        section_response = session.post(
            sections_url,
            json={"courseId": course_id, "sectionIds": section_ids},
            headers=headers,
            timeout=20,
        )
        section_calls += 1
        section_response.raise_for_status()
        parsed_sections, parse_stats = _parse_sections_response(
            payload=_safe_json(section_response),
            requested_identity=requested_identity,
            fallback_identity=fallback_identity if course_match == "matched" else None,
            location_match=location_match,
        )
        unknown += parse_stats.unknown
        dropped_nonmatch += parse_stats.dropped_nonmatch
        for section in parsed_sections:
            if section.section_id in seen_ids:
                continue
            seen_ids.add(section.section_id)
            sections.append(section)
    return sections, _MatchStats(
        matched=len(sections), unknown=unknown, dropped_nonmatch=dropped_nonmatch
    )


def _parse_sections_response(
    *,
    payload: dict[str, object],
    requested_identity: tuple[str, str] | None,
    fallback_identity: tuple[str, str] | None = None,
    location_match: str = "",
) -> tuple[list[ParsedSection], _MatchStats]:
    sections_retrieved = payload.get("SectionsRetrieved")
    if not isinstance(sections_retrieved, dict):
        return [], _MatchStats()
    out: list[ParsedSection] = []
    unknown = 0
    dropped_nonmatch = 0
    for term_entry in sections_retrieved.get("TermsAndSections") or []:
        if not isinstance(term_entry, dict):
            continue
        for wrapped in term_entry.get("Sections") or []:
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
                dropped_nonmatch += 1
                continue
            if section_match == "unknown":
                unknown += 1
                continue
            if not _location_ok(section_body, location_match):
                dropped_nonmatch += 1
                continue
            section = parse_section(section_body, wrapper=wrapped)
            if section is not None:
                out.append(section)
    return out, _MatchStats(matched=len(out), unknown=unknown, dropped_nonmatch=dropped_nonmatch)


def _is_clear_miss(
    catalog_payload: dict[str, object], requested_identity: tuple[str, str] | None
) -> bool:
    """True when the catalog listed this term's courses in the requested subject, and the
    requested course is not among them.

    The keyword search matches on subject, so rewording only the number ("MATH 70" for
    "MATH 070") returns the same list, and trying more keyword variants cannot turn up the
    course. An empty or other-subject listing proves nothing, and a full page may be
    truncated, so neither counts.
    """
    if requested_identity is None:
        return False
    models = [m for m in catalog_payload.get("CourseFullModels") or [] if isinstance(m, dict)]
    if len(models) >= _PAGE_SIZE:
        return False
    identities = [identity for m in models if (identity := _extract_catalog_identity(m))]
    same_subject = [i for i in identities if i[0] == requested_identity[0]]
    return bool(same_subject) and not any(
        _course_identities_match(requested_identity, i) for i in same_subject
    )


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


def _build_raw_summary(raw_summary: str, stats: _MatchStats) -> str:
    suffix = (
        f"[match_filter matched={stats.matched} "
        f"unknown={stats.unknown} dropped_nonmatch={stats.dropped_nonmatch}]"
    )
    if not _DEBUG_RAW_SUMMARY or not raw_summary:
        return suffix
    return f"{raw_summary[:400]}\n{suffix}"


def _coerce_total_pages(value: object) -> int:
    if isinstance(value, int):
        return max(value, 1)
    if isinstance(value, float):
        return max(int(value), 1)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return 1
        try:
            parsed = int(float(stripped))
        except ValueError:
            return 1
        return max(parsed, 1)
    return 1


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

    # CatalogListing's CourseFullModels carry the code at the top level, not under "Course".
    top_level = _normalize_identity(
        subject=_first_str(raw_row.get("SubjectCode")),
        number=_first_str(raw_row.get("Number")),
    )
    if top_level is not None:
        return top_level

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
        raw_summary=raw_summary,
    )
