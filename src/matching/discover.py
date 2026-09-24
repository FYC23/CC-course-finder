"""Offline discover pass (spec 9.2 steps 2-3): find this term's code for ASSIST courses the
resolver cannot match yet. Pure: the subject lister and decision backend are injected,
and the caller decides what to store. Runs from `matching discover`, never per search.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field

from src.decisions.questions import COURSE_EQUIVALENT, QUESTIONS, course_equivalent_state
from src.decisions.types import BooleanAnswer, DecisionProvider, DecisionUnavailable
from src.schedule.listing import ListedCourse, ListingUnsupported, SubjectLister, unique_courses
from src.schedule.models import CollegeScheduleSource
from src.schedule.term import ParsedTerm

from .codes import code_key, split_code, subject_key
from .config import ACCEPT_THRESHOLD, CANDIDATES_PER_COURSE, REVIEW_THRESHOLD
from .formerly import formerly_aliases
from .models import CourseAlias
from .resolve import CourseResolver
from .similarity import title_similarity

logger = logging.getLogger(__name__)

OUTCOME_STATUSES: tuple[str, ...] = (
    "matched", "formerly", "decided", "needs_decider", "needs_title",
    "no_candidates", "decider_unavailable", "listing_unsupported",
)
Pair = tuple[int, str, str]  # (cc_id, old code_key, new code_key)


@dataclass(frozen=True)
class AssistCourse:
    code: str
    title: str
    articulates_to: str


@dataclass(frozen=True)
class DiscoverOutcome:
    course_code: str
    status: str
    aliases: tuple[CourseAlias, ...] = ()
    note: str = ""


class _Listings:
    """One listing request per subject per run."""

    def __init__(self, lister: SubjectLister, source: CollegeScheduleSource, term: ParsedTerm) -> None:
        self._lister, self._source, self._term = lister, source, term
        self._cache: dict[str, tuple[ListedCourse, ...]] = {}

    def get(self, subject: str) -> tuple[ListedCourse, ...]:
        key = subject_key(subject)
        if key not in self._cache:
            self._cache[key] = self._lister.list_subject(source=self._source, term=self._term, subject=subject)
        return self._cache[key]


class _DeciderState:
    """Shares one decision backend across a run and remembers whether it has already
    failed, so a `DecisionUnavailable` from an earlier course stops further calls."""

    def __init__(self, decider: DecisionProvider | None) -> None:
        self.decider = decider
        self.unavailable_note: str | None = None


@dataclass(frozen=True)
class _Context:
    source: CollegeScheduleSource
    listings: _Listings
    resolver: CourseResolver
    decider_state: _DeciderState
    known_pairs: frozenset[Pair] = field(default_factory=frozenset)


def discover_aliases(
    *,
    source: CollegeScheduleSource,
    term: ParsedTerm,
    courses: Sequence[AssistCourse],
    lister: SubjectLister,
    resolver: CourseResolver,
    decider: DecisionProvider | None,
    known_pairs: frozenset[Pair] = frozenset(),
) -> tuple[DiscoverOutcome, ...]:
    """Thin wrapper over `iter_discover` for callers that want every outcome at once."""
    return tuple(iter_discover(
        source=source, term=term, courses=courses, lister=lister,
        resolver=resolver, decider=decider, known_pairs=known_pairs,
    ))


def iter_discover(
    *,
    source: CollegeScheduleSource,
    term: ParsedTerm,
    courses: Sequence[AssistCourse],
    lister: SubjectLister,
    resolver: CourseResolver,
    decider: DecisionProvider | None,
    known_pairs: frozenset[Pair] = frozenset(),
) -> Iterator[DiscoverOutcome]:
    """Yield each course's `DiscoverOutcome` as soon as it is decided, so a caller can
    store outcomes as they arrive instead of losing everything to a later error.

    If listing a subject raises `ListingUnsupported`, every course from that point on
    (the current one plus any not yet yielded) is reported `listing_unsupported`, since
    that error always fires on the first listing call for this college.
    """
    context = _Context(source, _Listings(lister, source, term), resolver, _DeciderState(decider), known_pairs)
    course_list = list(courses)
    for index, course in enumerate(course_list):
        try:
            yield _discover_one(context, course)
        except ListingUnsupported as err:
            for remaining in course_list[index:]:
                yield DiscoverOutcome(remaining.code, "listing_unsupported", note=str(err))
            return


def _discover_one(ctx: _Context, course: AssistCourse) -> DiscoverOutcome:
    parts = split_code(course.code)
    if parts is None:
        return DiscoverOutcome(course.code, "no_candidates", note="course code has no subject and number")
    cc_id = ctx.source.cc_id
    subjects = (parts[0], *ctx.resolver.renamed_subjects(cc_id, parts[0]))
    listed = unique_courses(item for subject in subjects for item in ctx.listings.get(subject))
    targets = {code_key(live.code) for live in ctx.resolver.live_codes(cc_id, course.code)}
    hit = next((item for item in listed if code_key(item.code) in targets), None)
    if hit is not None:
        return DiscoverOutcome(course.code, "matched", note=f"listed as {hit.code}")
    if ctx.resolver.has_alias(cc_id, course.code):
        return DiscoverOutcome(course.code, "matched", note="already mapped; the target is outside this listing")
    old_key = code_key(course.code)
    formerly = tuple(a for a in formerly_aliases(cc_id, listed) if a.old_key == old_key)
    if formerly:
        return DiscoverOutcome(course.code, "formerly", formerly)
    return _decide(ctx, course, listed)


def _decide(ctx: _Context, course: AssistCourse, listed: Sequence[ListedCourse]) -> DiscoverOutcome:
    state = ctx.decider_state
    if state.decider is None:
        note = "DECISION_PROVIDER=none; add an alias by hand or set a provider"
        logger.warning("discover needs_decider for cc_id=%s course=%s: %s", ctx.source.cc_id, course.code, note)
        return DiscoverOutcome(course.code, "needs_decider", note=note)
    if not course.title:
        return DiscoverOutcome(course.code, "needs_title", note="ASSIST row has no title; re-run the ASSIST ingest")
    candidates = rank_candidates(course, listed, cc_id=ctx.source.cc_id, known_pairs=ctx.known_pairs)
    if not candidates:
        return DiscoverOutcome(course.code, "no_candidates", note="nothing new to ask about in this listing")
    if state.unavailable_note is not None:
        note = f"decider unavailable earlier in this run: {state.unavailable_note}"
        return DiscoverOutcome(course.code, "decider_unavailable", note=note)
    try:
        scored = tuple(
            (item, _probability(ctx, course, item)) for item in candidates[:CANDIDATES_PER_COURSE]
        )
    except DecisionUnavailable as err:
        logger.warning(
            "discover decider_unavailable for cc_id=%s course=%s: %s", ctx.source.cc_id, course.code, err
        )
        state.unavailable_note = str(err)
        return DiscoverOutcome(course.code, "decider_unavailable", note=str(err))
    aliases = aliases_from_scores(ctx.source.cc_id, course, scored, state.decider.name)
    return DiscoverOutcome(course.code, "decided", aliases)


def _probability(ctx: _Context, course: AssistCourse, item: ListedCourse) -> float:
    state = course_equivalent_state(
        college=ctx.source.cc_name, assist_code=course.code, assist_title=course.title,
        articulates_to=course.articulates_to, live_code=item.code, live_title=item.title,
        live_description=item.description,
    )
    decider = ctx.decider_state.decider
    assert decider is not None  # guarded by the caller's `state.decider is None` check
    answer = decider.decide(state, {COURSE_EQUIVALENT: QUESTIONS[COURSE_EQUIVALENT]})[COURSE_EQUIVALENT]
    if not isinstance(answer, BooleanAnswer):
        raise DecisionUnavailable(f"course_equivalent answer was {type(answer).__name__}, not BooleanAnswer")
    return answer.probability


def rank_candidates(
    course: AssistCourse, listed: Iterable[ListedCourse], *, cc_id: int, known_pairs: frozenset[Pair]
) -> tuple[ListedCourse, ...]:
    old_key = code_key(course.code)
    fresh = [item for item in listed if (cc_id, old_key, code_key(item.code)) not in known_pairs]
    return tuple(sorted(fresh, key=lambda item: (-title_similarity(course.title, item.title), item.code)))


def aliases_from_scores(
    cc_id: int,
    course: AssistCourse,
    scored: Iterable[tuple[ListedCourse, float]],
    decider_name: str,
) -> tuple[CourseAlias, ...]:
    ranked = sorted(scored, key=lambda pair: -pair[1])
    aliases: list[CourseAlias] = []
    for index, (item, probability) in enumerate(ranked):
        if index == 0 and probability >= ACCEPT_THRESHOLD:
            status = "accepted"
        elif probability >= REVIEW_THRESHOLD:
            status = "review"
        else:
            status = "rejected"
        aliases.append(CourseAlias(
            cc_id=cc_id, old_code=course.code, new_code=item.code, source=f"decision:{decider_name}",
            status=status, confidence=round(probability, 4),
            evidence=f"{course.code} '{course.title}' vs {item.code} '{item.title}'; p={probability:.3f}",
        ))
    return tuple(aliases)
