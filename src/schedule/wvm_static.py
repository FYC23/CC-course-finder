from __future__ import annotations

import re

import requests

from .models import CollegeScheduleSource, CourseAvailability, ParsedSection
from .term import ParsedTerm

_SEASON_CODE = {"spring": "30", "summer": "50", "fall": "70"}

_MODALITY_MAP = {
    "AON": "online",
    "SON": "online",
    "INP": "in_person",
    "HYB": "hybrid",
    "FLX": "hybrid",
}

_COURSE_CODE_RE = re.compile(r"^\s*([A-Za-z]+)\s*[- ]?\s*([A-Za-z0-9]+)\s*$")


def _term_to_wvm_code(term: ParsedTerm) -> str:
    return f"{term.year}{_SEASON_CODE[term.season]}"


def _parse_course_code(course_code: str) -> tuple[str, str] | None:
    m = _COURSE_CODE_RE.match(course_code)
    if not m:
        return None
    return m.group(1).upper(), m.group(2).upper().lstrip("0") or "0"


def _normalize_crse(crse: str) -> str:
    return crse.upper().lstrip("0") or "0"


class WvmStaticProvider:
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._crns_cache: dict[tuple[str, str], list[dict]] = {}
        self._instructors_cache: dict[tuple[str, str], dict[str, str]] = {}

    def supports_source(self, source: CollegeScheduleSource) -> bool:
        return source.system == "wvm_static"

    def search_course(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, course_code: str
    ) -> CourseAvailability:
        if not self.supports_source(source):
            raise ValueError(
                f"WvmStaticProvider does not support system={source.system!r}"
            )

        term_code = _term_to_wvm_code(term)
        cache_key = (source.base_url, term_code)
        crns_url = f"{source.base_url}/data/{term_code}/crns.json"

        if cache_key not in self._crns_cache:
            resp = self._session.get(crns_url, timeout=20)
            resp.raise_for_status()
            self._crns_cache[cache_key] = resp.json()

        all_rows: list[dict] = self._crns_cache[cache_key]

        parsed = _parse_course_code(course_code)
        if parsed is None:
            return _build(source=source, term=term, course_code=course_code,
                          sections=[], source_url=crns_url, raw_summary="parse error")

        subj, crse = parsed
        locations = set(source.locations)
        matching = [
            r for r in all_rows
            if r.get("SUBJ_CODE", "").upper() == subj
            and _normalize_crse(str(r.get("CRSE_NUMB", ""))) == crse
            and (not locations or r.get("SSBSECT_CAMP_CODE", "") in locations)
        ]

        if not matching:
            return _build(source=source, term=term, course_code=course_code,
                          sections=[], source_url=crns_url,
                          raw_summary="0 sections found")

        if cache_key not in self._instructors_cache:
            instr_url = f"{source.base_url}/data/{term_code}/section-instructors.json"
            resp = self._session.get(instr_url, timeout=20)
            resp.raise_for_status()
            raw: list[dict] = resp.json()
            self._instructors_cache[cache_key] = {
                str(r["SIRASGN_CRN"]): r.get("INSTRUCTOR_NAME", "") for r in raw
            }

        instructors = self._instructors_cache[cache_key]

        sections: list[ParsedSection] = []
        for row in matching:
            crn = str(row.get("CRN", ""))
            insm = row.get("SSBSECT_INSM_CODE", "")
            modality = _MODALITY_MAP.get(insm, "unknown")
            seats = row.get("SSBSECT_SEATS_AVAIL", 0)
            status = "open" if (seats or 0) > 0 else "closed"
            sections.append(ParsedSection(
                section_id=crn,
                status=status,
                modality=modality,
                title=row.get("SSBSECT_CRSE_TITLE") or row.get("CRSE_TITLE", ""),
                instructor=instructors.get(crn, ""),
            ))

        return _build(
            source=source, term=term, course_code=course_code,
            sections=sections, source_url=crns_url,
            raw_summary=f"{len(sections)} section(s) found",
        )


def _build(
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
