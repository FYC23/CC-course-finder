from __future__ import annotations

import re
from html import unescape

import requests

from .colleague import (
    build_availability,
    course_matches,
    normalize_modality,
    normalize_status,
    parse_requested_course,
)
from .models import CollegeScheduleSource, CourseAvailability, ParsedSection
from .term import ParsedTerm

_TERM_OPTION_RE = re.compile(
    r'<option[^>]*value="([0-9]+)"[^>]*>\s*(Spring|Summer|Fall)\s+([0-9]{4})\s*</option>',
    re.IGNORECASE,
)


class MarinColleagueProvider:
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def supports_source(self, source: CollegeScheduleSource) -> bool:
        return source.system == "marin_colleague"

    def search_course(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, course_code: str
    ) -> CourseAvailability:
        if not self.supports_source(source):
            msg = (
                "Provider MarinColleagueProvider does not support source system="
                f"{source.system!r} for cc_id={source.cc_id}"
            )
            raise ValueError(msg)

        requested = parse_requested_course(course_code)
        landing = self._session.get(source.base_url, timeout=25)
        landing.raise_for_status()
        term_code = _resolve_term_code(landing.text, term)

        campus = source.locations[0] if source.locations else "0000"
        department = requested.subject
        params = {
            "TermCode": term_code,
            "CampusCode": campus,
            "SessionCode": "0",
            "SubjectCode": department,
        }
        response = self._session.get(source.base_url, params=params, timeout=25)
        response.raise_for_status()

        sections = _parse_sections(response.text, requested_subject_number=course_code)
        return build_availability(
            source=source,
            term=term,
            course_code=course_code,
            sections=sections,
            source_url=response.url,
            raw_summary=f"[marin_colleague sections={len(sections)}]",
        )


def _resolve_term_code(html: str, term: ParsedTerm) -> str:
    label = term.label.lower()
    for code, season, year in _TERM_OPTION_RE.findall(html):
        option_label = f"{season.lower()} {year}"
        if option_label == label:
            return code
    raise ValueError(f"Unable to resolve Marin term code for {term.label!r}")


def _parse_sections(html: str, *, requested_subject_number: str) -> list[ParsedSection]:
    table_match = re.search(
        r'<table[^>]*id="MainContent_grdSchedule"[^>]*>(?P<body>[\s\S]*?)</table>',
        html,
        flags=re.IGNORECASE,
    )
    if table_match is None:
        return []

    rows = re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", table_match.group("body"), re.IGNORECASE)
    requested = parse_requested_course(requested_subject_number)
    out: list[ParsedSection] = []
    for row_html in rows[1:]:
        cells = re.findall(r"<td[^>]*>([\s\S]*?)</td>", row_html, re.IGNORECASE)
        if len(cells) < 13:
            continue
        section_id = _cell_text(cells[1])
        course = _cell_text(cells[2])
        if not section_id or not course_matches(requested, course):
            continue
        campus = _cell_text(cells[9])
        section_type = _cell_text(cells[11])
        instructor = _cell_text(cells[12])
        out.append(
            ParsedSection(
                section_id=section_id,
                status=normalize_status(None),
                modality=normalize_modality(campus=campus, section_type=section_type),
                title=course,
                instructor=instructor,
            )
        )
    return out


def _cell_text(cell_html: str) -> str:
    stripped = re.sub(r"<[^>]+>", " ", cell_html)
    return " ".join(unescape(stripped).split())
