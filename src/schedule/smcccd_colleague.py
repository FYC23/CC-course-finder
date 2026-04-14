from __future__ import annotations

import os

import requests

from .colleague import (
    build_availability,
    normalize_modality,
    normalize_status,
    parse_course_identity,
    parse_requested_course,
)
from .models import CollegeScheduleSource, CourseAvailability, ParsedSection
from .term import ParsedTerm

_AUTH_ERROR = (
    "SMCCD schedule API requires basic auth credentials "
    "(set SMCCD_API_USERNAME and SMCCD_API_PASSWORD)"
)


class SmcccdColleagueProvider:
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def supports_source(self, source: CollegeScheduleSource) -> bool:
        return source.system == "smcccd_colleague"

    def search_course(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, course_code: str
    ) -> CourseAvailability:
        if not self.supports_source(source):
            msg = (
                "Provider SmcccdColleagueProvider does not support source system="
                f"{source.system!r} for cc_id={source.cc_id}"
            )
            raise ValueError(msg)

        username = os.getenv("SMCCD_API_USERNAME", "").strip()
        password = os.getenv("SMCCD_API_PASSWORD", "").strip()
        if not username or not password:
            raise ValueError(_AUTH_ERROR)

        requested = parse_requested_course(course_code)
        params = {
            "s": course_code,
            "term_desc": term.label,
            "college_desc": source.locations[0] if source.locations else "college of san mateo",
            "limit": 200,
        }
        response = self._session.get(
            f"{source.base_url.rstrip('/')}/courses",
            params=params,
            auth=(username, password),
            timeout=25,
            headers={"Accept": "application/hal+json"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise requests.RequestException("SMCCD API returned invalid JSON payload")

        sections: list[ParsedSection] = []
        for raw_course in payload.get("_embedded", {}).get("course", []):
            if not isinstance(raw_course, dict):
                continue
            candidate = parse_course_identity(
                f"{raw_course.get('subject_code', '')} {raw_course.get('course_number', '')}"
            )
            if (
                candidate is None
                or candidate.subject != requested.subject
                or candidate.number != requested.number
            ):
                continue
            status = normalize_status(str(raw_course.get("status", "")))
            title = str(raw_course.get("title", "")).strip()
            crn = str(raw_course.get("crn", "")).strip()

            raw_sections = raw_course.get("sections", [])
            if not isinstance(raw_sections, list):
                raw_sections = []
            if not raw_sections:
                sections.append(
                    ParsedSection(
                        section_id=crn or "unknown",
                        status=status,
                        modality="unknown",
                        title=title,
                        instructor="",
                    )
                )
                continue

            for raw_section in raw_sections:
                if not isinstance(raw_section, dict):
                    continue
                section_sequence = str(raw_section.get("section_sequence", "")).strip()
                location = raw_section.get("location", {})
                campus = (
                    str(location.get("college_description", ""))
                    if isinstance(location, dict)
                    else ""
                )
                schedule_description = str(
                    raw_section.get("schedule_description", "")
                ).strip()
                instructor_data = raw_section.get("instructor", {})
                instructor_name = (
                    str(instructor_data.get("name", "")).strip()
                    if isinstance(instructor_data, dict)
                    else ""
                )
                sections.append(
                    ParsedSection(
                        section_id=f"{crn}-{section_sequence}".strip("-"),
                        status=status,
                        modality=normalize_modality(
                            campus=campus, section_type=schedule_description
                        ),
                        title=title,
                        instructor=instructor_name,
                    )
                )

        return build_availability(
            source=source,
            term=term,
            course_code=course_code,
            sections=sections,
            source_url=response.url,
            raw_summary=f"[smcccd_colleague sections={len(sections)}]",
        )
