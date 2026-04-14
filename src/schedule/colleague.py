from __future__ import annotations

import re
from dataclasses import dataclass

from .models import CollegeScheduleSource, CourseAvailability, ParsedSection
from .term import ParsedTerm

_COURSE_RE = re.compile(r"^\s*([A-Za-z]+)\s*[- ]\s*([A-Za-z0-9]+)\b")
_NUMBER_RE = re.compile(r"^([0-9]+)([A-Za-z]?)$")

_STATUS_MAP = {
    "open": "open",
    "closed": "closed",
    "cancelled": "closed",
    "canceled": "closed",
}


@dataclass(frozen=True)
class CourseIdentity:
    subject: str
    number: str


def parse_course_identity(text: str) -> CourseIdentity | None:
    match = _COURSE_RE.match(text.strip())
    if match is None:
        return None
    raw_number = match.group(2)
    if not any(ch.isdigit() for ch in raw_number):
        return None
    return CourseIdentity(
        subject=_normalize_token(match.group(1)),
        number=_normalize_number(raw_number),
    )


def parse_requested_course(course_code: str) -> CourseIdentity:
    parsed = parse_course_identity(course_code.replace(" ", "-", 1))
    if parsed is None:
        msg = f"Unsupported course code format: {course_code!r}"
        raise ValueError(msg)
    return parsed


def course_matches(requested: CourseIdentity, title_or_code: str) -> bool:
    parsed = parse_course_identity(title_or_code)
    if parsed is None:
        return False
    return parsed.subject == requested.subject and parsed.number == requested.number


def normalize_status(raw_status: str | None) -> str:
    if not raw_status:
        return "unknown"
    return _STATUS_MAP.get(raw_status.strip().lower(), "unknown")


def normalize_modality(*, campus: str, section_type: str) -> str:
    text = f"{campus} {section_type}".lower()
    if "hybrid" in text:
        return "hybrid"
    if "online" in text or "web" in text:
        return "online"
    return "in_person"


def build_availability(
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


def _normalize_token(token: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", token).upper()


def _normalize_number(token: str) -> str:
    candidate = _normalize_token(token)
    number_match = _NUMBER_RE.match(candidate)
    if number_match is None:
        return candidate
    digits, suffix = number_match.groups()
    return f"{digits.lstrip('0') or '0'}{suffix}"
