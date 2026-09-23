from __future__ import annotations

import re
from urllib.parse import urlsplit

import requests

from .models import CollegeScheduleSource, CourseAvailability, Meeting, ParsedSection
from .normalize import days_from_flags, int_or_none, normalize_modality, parse_date, parse_hhmm
from .term import ParsedTerm, term_match_rank

_PAGE_SIZE = 100
_COURSE_CODE_RE = re.compile(r"^\s*([A-Za-z]+)\s*[- ]?\s*([A-Za-z0-9]+)\s*$")
_VIEW_ONLY_RE = re.compile(r"\s*\(View Only\)\s*$", re.IGNORECASE)


def _base_root(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return url


def _resolve_term_code(session: requests.Session, base: str, term: ParsedTerm) -> str:
    """Fetch term list from SSB and match by label (case-insensitive, strips View Only)."""
    url = f"{base}/StudentRegistrationSsb/ssb/classSearch/getTerms"
    resp = session.get(url, params={"searchTerm": "", "offset": 1, "max": 50}, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, list):
        raise ValueError(f"SSB term list at {base} was not a JSON array")
    best: tuple[int, str] | None = None
    for entry in payload:
        if not isinstance(entry, dict) or "code" not in entry:
            continue
        desc = _VIEW_ONLY_RE.sub("", entry.get("description", "")).strip()
        rank = term_match_rank(term, desc)
        if rank is None:
            continue
        if best is None or rank < best[0]:
            best = (rank, str(entry["code"]))
    if best is not None:
        return best[1]
    raise ValueError(f"Term {term.label!r} not found in SSB term list at {base}")


def _parse_course_code(course_code: str) -> tuple[str, str] | None:
    m = _COURSE_CODE_RE.match(course_code)
    if not m:
        return None
    return m.group(1).upper(), m.group(2).upper()


_DAY_KEYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_ONLINE_LOCATION_HINTS = ("online", "web", "internet", "distance")


def _parse_meeting(meeting_time: dict) -> Meeting:
    building = str(meeting_time.get("buildingDescription") or meeting_time.get("building") or "").strip()
    room = str(meeting_time.get("room") or "").strip()
    location = " ".join(part for part in (building, room) if part)
    start = parse_hhmm(meeting_time.get("beginTime"))
    end = parse_hhmm(meeting_time.get("endTime"))
    looks_online = any(hint in location.lower() for hint in _ONLINE_LOCATION_HINTS)
    is_online = looks_online or (start is None and not room)
    return Meeting(
        days=days_from_flags({k: meeting_time.get(k) for k in _DAY_KEYS}),
        start_local=start,
        end_local=end,
        location=location,
        is_online=is_online,
        start_date=parse_date(meeting_time.get("startDate")),
        end_date=parse_date(meeting_time.get("endDate")),
    )


def _meetings_of(row: dict) -> tuple[Meeting, ...]:
    out: list[Meeting] = []
    for entry in row.get("meetingsFaculty") or []:
        meeting_time = entry.get("meetingTime") if isinstance(entry, dict) else None
        if isinstance(meeting_time, dict):
            out.append(_parse_meeting(meeting_time))
    return tuple(out)


def _status_of(row: dict) -> str:
    seats = int_or_none(row.get("seatsAvailable"))
    wait_capacity = int_or_none(row.get("waitCapacity")) or 0
    if not row.get("openSection"):
        return "closed"
    if seats is not None and seats <= 0:
        return "waitlist" if wait_capacity > 0 else "closed"
    return "open"


def _instructor_of(row: dict) -> str:
    names = [
        str(f.get("displayName")).strip()
        for f in row.get("faculty") or []
        if isinstance(f, dict) and f.get("displayName")
    ]
    return ", ".join(names)


def _parse_row(row: dict) -> ParsedSection:
    meetings = _meetings_of(row)
    method = row.get("instructionalMethodDescription") or row.get("instructionalMethod") or ""
    subject = str(row.get("subject") or "").strip()
    number = str(row.get("courseNumber") or "").strip()
    return ParsedSection(
        section_id=str(row.get("courseReferenceNumber", "")),
        status=_status_of(row),
        modality=normalize_modality(raw_tokens=[str(method)], meetings=meetings),
        title=str(row.get("courseTitle", "")),
        instructor=_instructor_of(row),
        meetings=meetings,
        seats_total=int_or_none(row.get("maximumEnrollment")),
        seats_used=int_or_none(row.get("enrollment")),
        course_code_as_listed=f"{subject} {number}".strip(),
    )


def _row_matches_campus(row: dict, codes: tuple[str, ...]) -> bool:
    """Keep rows with no campus information. Filter by campus codes if present."""
    if not codes:
        return True
    campuses = {
        str(meeting_time.get("campus") or "").upper()
        for entry in row.get("meetingsFaculty") or []
        if isinstance(entry, dict)
        for meeting_time in [entry.get("meetingTime")]
        if isinstance(meeting_time, dict)
    }
    campuses.discard("")
    if not campuses:
        return True
    return any(c in campuses for c in codes)


def _campus_codes(source: CollegeScheduleSource) -> tuple[str, ...]:
    raw = source.params.get("campus_codes", "")
    return tuple(code.strip().upper() for code in raw.split(",") if code.strip())


class Banner9SsbProvider:
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._session.headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        )
        self._term_cache: dict[tuple[str, str], str] = {}

    def supports_source(self, source: CollegeScheduleSource) -> bool:
        return source.system == "banner9_ssb"

    def search_course(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, course_code: str
    ) -> CourseAvailability:
        if not self.supports_source(source):
            raise ValueError(
                f"Banner9SsbProvider does not support system={source.system!r}"
            )

        base = _base_root(source.base_url)
        cache_key = (base, term.label)
        if cache_key not in self._term_cache:
            self._term_cache[cache_key] = _resolve_term_code(self._session, base, term)
        term_code = self._term_cache[cache_key]

        parsed = _parse_course_code(course_code)
        subject, number = parsed if parsed else (course_code, "")

        # Establish session cookie + set term
        self._session.get(
            f"{base}/StudentRegistrationSsb/ssb/term/termSelection",
            params={"mode": "search"},
            timeout=20,
        )
        self._session.post(
            f"{base}/StudentRegistrationSsb/ssb/term/search",
            params={"mode": "search"},
            data={"term": term_code},
            timeout=20,
        )

        sections: list[ParsedSection] = []
        page_offset = 0
        source_url = f"{base}/StudentRegistrationSsb/ssb/searchResults/searchResults"
        total_count = 0
        result_url = source_url

        while True:
            resp = self._session.get(
                source_url,
                params={
                    "txt_subject": subject,
                    "txt_courseNumber": number,
                    "txt_term": term_code,
                    "startDatepicker": "",
                    "endDatepicker": "",
                    "pageOffset": page_offset,
                    "pageMaxSize": _PAGE_SIZE,
                    "sortColumn": "subjectDescription",
                    "sortDirection": "asc",
                },
                timeout=20,
            )
            result_url = str(resp.url)
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, dict):
                raise requests.RequestException(
                    f"Unexpected non-object search response from {result_url}"
                )
            data = payload.get("data") or []

            codes = _campus_codes(source)
            for row in data:
                if not isinstance(row, dict) or not _row_matches_campus(row, codes):
                    continue
                sections.append(_parse_row(row))

            total_count = int_or_none(payload.get("totalCount")) or 0
            page_offset += len(data)
            if page_offset >= total_count or not data:
                break

        raw_summary = f"{len(sections)} section(s) found (totalCount={total_count})"

        return CourseAvailability(
            cc_id=source.cc_id,
            cc_name=source.cc_name,
            term=term.label,
            course_code=course_code,
            offered=bool(sections),
            sections=sections,
            source_url=result_url,
            raw_summary=raw_summary,
        )
