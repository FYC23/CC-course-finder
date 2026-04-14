from __future__ import annotations

import re
from urllib.parse import urlsplit

import requests

from .models import CollegeScheduleSource, CourseAvailability, ParsedSection
from .term import ParsedTerm

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
    needle = term.label.lower()
    for entry in resp.json():
        desc = _VIEW_ONLY_RE.sub("", entry.get("description", "")).strip().lower()
        if desc == needle:
            return str(entry["code"])
    raise ValueError(f"Term {term.label!r} not found in SSB term list at {base}")


def _parse_course_code(course_code: str) -> tuple[str, str] | None:
    m = _COURSE_CODE_RE.match(course_code)
    if not m:
        return None
    return m.group(1).upper(), m.group(2).upper()


class BannerSsbClassicProvider:
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._session.headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        )
        self._term_cache: dict[tuple[str, str], str] = {}

    def supports_source(self, source: CollegeScheduleSource) -> bool:
        return source.system == "banner_ssb_classic"

    def search_course(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, course_code: str
    ) -> CourseAvailability:
        if not self.supports_source(source):
            raise ValueError(
                f"BannerSsbClassicProvider does not support system={source.system!r}"
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
            data = payload.get("data") or []

            for row in data:
                status = "open" if row.get("openSection") else "closed"
                sections.append(
                    ParsedSection(
                        section_id=str(row.get("courseReferenceNumber", "")),
                        status=status,
                        modality="unknown",
                        title=str(row.get("courseTitle", "")),
                        instructor="",
                    )
                )

            total = payload.get("totalCount") or 0
            total_count = int(total or 0)
            page_offset += len(data)
            if page_offset >= total or not data:
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
