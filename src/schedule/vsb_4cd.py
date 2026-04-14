from __future__ import annotations

import math
import time
import xml.etree.ElementTree as ET

import requests
from urllib.parse import quote

from .models import CollegeScheduleSource, CourseAvailability, ParsedSection
from .term import ParsedTerm

_BASE_URL = "https://vsb.4cd.edu"
_TERM_SUFFIXES = {"spring": "30", "summer": "10", "fall": "20"}

# instruction mode codes from VSB
_IM_MAP = {"01": "online", "02": "hybrid", "03": "in-person"}


def _term_code(term: ParsedTerm) -> str:
    suffix = _TERM_SUFFIXES.get(term.season)
    if suffix is None:
        raise ValueError(f"Unsupported season {term.season!r} for VSB term code")
    # Spring belongs to the *next* calendar year in VSB (e.g. Spring 2026 → 202630)
    # but VSB labels it as the year stated, so use term.year directly
    return f"{term.year}{suffix}"


def _nwindow() -> str:
    t = int(math.floor(time.time() / 60)) % 1000
    e = t % 3 + t % 39 + t % 42
    return f"&t={t}&e={e}"


def _course_key(course_code: str) -> str:
    """'MATH 220' → 'MATH-220'"""
    return course_code.strip().replace(" ", "-").upper()


class Vsb4cdProvider:
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._session.headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        )

    def supports_source(self, source: CollegeScheduleSource) -> bool:
        return source.system == "vsb_4cd"

    def search_course(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, course_code: str
    ) -> CourseAvailability:
        if not self.supports_source(source):
            raise ValueError(
                f"Vsb4cdProvider does not support system={source.system!r}"
            )

        term_code = _term_code(term)
        ck = _course_key(course_code)
        campus = source.locations[0]  # e.g. "LMC", "CCC", "DVC"

        url = (
            f"{_BASE_URL}/api/class-data"
            f"?term={term_code}"
            f"&course_0_0={quote(ck)}"
            f"&va_0_0=&rq_0_0=&nouser=1"
            f"{_nwindow()}"
        )

        resp = self._session.get(url, timeout=20)
        resp.raise_for_status()

        sections = _parse_sections(resp.text, campus)
        raw_summary = f"{len(sections)} section(s) found for campus={campus}"

        return CourseAvailability(
            cc_id=source.cc_id,
            cc_name=source.cc_name,
            term=term.label,
            course_code=course_code,
            offered=bool(sections),
            sections=sections,
            source_url=url,
            raw_summary=raw_summary,
        )


def _parse_sections(xml_text: str, campus: str) -> list[ParsedSection]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    classdata = root.find("classdata")
    if classdata is None:
        return []

    sections: list[ParsedSection] = []
    for course in classdata.findall("course"):
        for usel in course.findall("uselection"):
            # Each uselection = one enrollable section; pick the primary block (has im set)
            primary = None
            for block in usel.findall("selection/block"):
                if block.get("campus", "").upper() != campus.upper():
                    continue
                if block.get("im", ""):  # non-empty im = primary instructional block
                    primary = block
                    break
            if primary is None:
                continue
            is_full = primary.get("isFull", "0") == "1"
            open_seats = int(primary.get("os", "-1"))
            status = "open" if not is_full and open_seats != 0 else "closed"
            modality = _IM_MAP.get(primary.get("im", ""), "unknown")
            sel = usel.find("selection")
            sections.append(
                ParsedSection(
                    section_id=str(primary.get("secNo", primary.get("key", ""))),
                    status=status,
                    modality=modality,
                    title=sel.get("thc", "") if sel is not None else "",
                    instructor=primary.get("teacher", ""),
                )
            )
    return sections
