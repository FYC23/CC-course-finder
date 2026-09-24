"""Turn one ASSIST course's lookups under each live code back into one CourseAvailability.

The course matcher (src/matching) gives the codes a college may list a course under this
term; ScheduleService asks the provider once per code. The merged result is keyed by the
ASSIST code, so the web join still lines up with the ASSIST row, and records which alias
found the sections.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

import requests

from src.matching.resolve import LiveCode

from .errors import PortalChanged, SpecUnavailable
from .models import CollegeScheduleSource, CourseAvailability, ParsedSection
from .term import ParsedTerm, TermNotListedError


@dataclass(frozen=True)
class Attempt:
    live: LiveCode
    availability: CourseAvailability | None = None
    error: Exception | None = None
    skipped: bool = False


def merge_attempts(
    *, source: CollegeScheduleSource, term: ParsedTerm, course_code: str, attempts: Sequence[Attempt]
) -> CourseAvailability:
    if not attempts:
        raise ValueError("merge_attempts needs at least one attempt")
    found = [a for a in attempts if a.availability is not None]
    offered = [a for a in found if a.availability.sections]
    many = len(attempts) > 1
    if offered:
        return _offered(course_code, offered, found, many=many)
    failed = [a for a in attempts if a.error is not None]
    if failed:
        return failed_availability(source, term, course_code, failed[0].error, skipped=failed[0].skipped)
    return replace(found[0].availability, course_code=course_code, raw_summary=_summary(found, many=many))


def _offered(
    course_code: str, offered: list[Attempt], found: list[Attempt], *, many: bool
) -> CourseAvailability:
    alias = next((a.live for a in offered if a.live.is_alias), None)
    return replace(
        offered[0].availability,
        course_code=course_code,
        offered=True,
        sections=_pooled_sections(offered),
        raw_summary=_summary(found, many=many),
        matched_code=alias.code if alias else "",
        match_source=alias.source if alias else "",
        match_status=alias.status if alias else "",
    )


def _pooled_sections(attempts: list[Attempt]) -> list[ParsedSection]:
    seen: set[tuple[str, str]] = set()
    pooled: list[ParsedSection] = []
    for attempt in attempts:
        for section in attempt.availability.sections:
            key = (section.course_code_as_listed or attempt.live.code, section.section_id)
            if key not in seen:
                seen.add(key)
                pooled.append(section)
    return pooled


def _summary(found: list[Attempt], *, many: bool) -> str:
    if not many:
        return found[0].availability.raw_summary
    return " | ".join(f"{a.live.code}: {a.availability.raw_summary}" for a in found)


def failed_availability(
    source: CollegeScheduleSource,
    term: ParsedTerm,
    course_code: str,
    err: Exception,
    *,
    skipped: bool,
) -> CourseAvailability:
    summary = f"[request_error type={type(err).__name__}]"
    if skipped:
        summary = f"[skipped: college unreachable earlier in this search; {summary[1:]}"
    return CourseAvailability(
        cc_id=source.cc_id,
        cc_name=source.cc_name,
        term=term.label,
        course_code=course_code,
        offered=False,
        sections=[],
        source_url=source.base_url,
        raw_summary=summary,
        lookup_error=lookup_error_reason(err, term),
    )


def lookup_error_reason(err: Exception, term: ParsedTerm) -> str:
    """A student-facing reason the course could not be checked (no internals leaked)."""
    if isinstance(err, requests.ConnectionError):
        return "Couldn't reach the college's schedule server."
    if isinstance(err, requests.Timeout):
        return "The college's schedule server took too long to answer."
    if isinstance(err, requests.HTTPError):
        return "The college's schedule server returned an error."
    if isinstance(err, TermNotListedError):
        return f"{term.label} isn't listed on the college's schedule site."
    if isinstance(err, SpecUnavailable):
        return "This college's schedule lookup is unavailable right now."
    if isinstance(err, PortalChanged):
        return "The college's schedule site changed; this lookup needs to be re-recorded."
    return "Something went wrong reading the college's schedule."
