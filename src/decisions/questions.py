"""The questions the project asks a decision backend, defined once so both backends and
the eval share them (spec section 8.2). Onboarding questions arrive with Phase 4."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from src.schedule.models import MODALITIES

from .types import Boolean, Choice, Question

COURSE_EQUIVALENT = "course_equivalent"
SECTION_MODALITY = "section_modality"
_MAX_DESCRIPTION_CHARS = 1200

_MODALITY_CRITERIA: Mapping[str, str] = MappingProxyType({
    "async_online": "Fully online with no scheduled class meetings (asynchronous, 'internet delayed').",
    "sync_online": "Fully online with live meetings at scheduled times (Zoom, 'online synchronous').",
    "hybrid": "Part online and part in person on campus.",
    "in_person": "Meets in person at a campus or off-campus site.",
    "unknown": "The data does not say how the section is taught.",
})
assert tuple(_MODALITY_CRITERIA) == MODALITIES

QUESTIONS: Mapping[str, Question] = MappingProxyType({
    COURSE_EQUIVALENT: Boolean(
        instructions=(
            "Is the live schedule course the same course as the ASSIST course, only renumbered "
            "or renamed (for example by California Common Course Numbering), so that taking "
            "the live course satisfies the same transfer articulation? Say yes only when the "
            "subject matter and level clearly match. A different course in the same subject "
            "(Calculus I versus Calculus II, a support course, an honors variant of another "
            "course) is no."
        )
    ),
    SECTION_MODALITY: Choice(
        instructions="How is this class section taught?",
        criteria=_MODALITY_CRITERIA,
    ),
})


def course_equivalent_state(
    *,
    college: str,
    assist_code: str,
    assist_title: str,
    articulates_to: str,
    live_code: str,
    live_title: str,
    live_description: str,
) -> Mapping[str, object]:
    return MappingProxyType({
        "college": college,
        "assist_course": MappingProxyType(
            {"code": assist_code, "title": assist_title, "articulates_to": articulates_to}
        ),
        "live_course": MappingProxyType({
            "code": live_code,
            "title": live_title,
            "description": live_description[:_MAX_DESCRIPTION_CHARS],
        }),
    })


def section_modality_state(
    *, raw_tokens: Sequence[str], locations: Sequence[str], has_timed_meetings: bool
) -> Mapping[str, object]:
    return MappingProxyType({
        "raw_modality_tokens": tuple(raw_tokens),
        "meeting_locations": tuple(locations),
        "has_timed_meetings": has_timed_meetings,
    })
