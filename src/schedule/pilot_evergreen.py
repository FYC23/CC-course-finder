from __future__ import annotations

import re

import requests

from .models import CollegeScheduleSource, CourseAvailability, ParsedSection
from .term import ParsedTerm

_ROW_RE = re.compile(
    r"CRN:(?P<crn>[^|]+)\|STATUS:(?P<status>[^|]+)\|MODALITY:(?P<modality>[^|]+)\|TITLE:(?P<title>[^|]+)\|INSTRUCTOR:(?P<instructor>[^\n]+)"
)

_STATUS_MAP = {"open": "open", "closed": "closed"}
_MODALITY_MAP = {
    "online": "online",
    "in person": "in_person",
    "hybrid": "hybrid",
}


class EvergreenBannerProvider:
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def search_course(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, course_code: str
    ) -> CourseAvailability:
        response = self._session.get(
            source.base_url,
            params={
                "Terms": _term_to_banner_code(term),
                "locations": "EVC",
                "keyword": course_code,
            },
            timeout=20,
        )
        response.raise_for_status()
        sections = _parse_sections(response.text)
        return CourseAvailability(
            cc_id=source.cc_id,
            cc_name=source.cc_name,
            term=term.label,
            course_code=course_code,
            offered=bool(sections),
            sections=sections,
            source_url=response.url,
            raw_summary=response.text[:500],
        )


def _term_to_banner_code(term: ParsedTerm) -> str:
    season_to_code = {"spring": "SP", "summer": "SU", "fall": "FA"}
    season_code = season_to_code.get(term.season)
    if season_code is None:
        raise ValueError(f"Unsupported season for banner mapping: {term.season}")
    return f"{term.year}{season_code}"


def _parse_sections(body: str) -> list[ParsedSection]:
    sections: list[ParsedSection] = []
    for match in _ROW_RE.finditer(body):
        status = _STATUS_MAP.get(match.group("status").strip().lower(), "unknown")
        modality = _MODALITY_MAP.get(match.group("modality").strip().lower(), "unknown")
        sections.append(
            ParsedSection(
                section_id=match.group("crn").strip(),
                status=status,
                modality=modality,
                title=match.group("title").strip(),
                instructor=match.group("instructor").strip(),
            )
        )
    return sections
