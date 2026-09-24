from __future__ import annotations

import json
import logging
from pathlib import Path

from src.decisions.questions import COURSE_EQUIVALENT
from src.decisions.types import BooleanAnswer, DecisionUnavailable
from src.matching.discover import (
    AssistCourse, aliases_from_scores, discover_aliases, rank_candidates,
)
from src.matching.models import CourseAlias, SubjectRename
from src.matching.resolve import CourseResolver
from src.schedule.catalog import get_college_source
from src.schedule.colleague_listing import parse_catalog_listing
from src.schedule.listing import ListedCourse, ListingUnsupported
from src.schedule.term import parse_term_label

_TERM = parse_term_label("Fall 2026")
_FRESNO = get_college_source(35)
_RIVERSIDE = get_college_source(78)
_CATALOG = parse_catalog_listing(json.loads(
    (Path(__file__).parents[1] / "fixtures" / "colleague" / "fcc_math_catalog.json").read_text()
))
_RCC_MATH = (
    ListedCourse("MATH-1C", "Calculus III"),
    ListedCourse("MATH-C2210", "Calculus I: Early Transcendentals"),
    ListedCourse("MATH-C2220", "Calculus II: Early Transcendentals"),
)


class _Lister:
    def __init__(self, by_subject):
        self.by_subject, self.calls = by_subject, []

    def list_subject(self, *, source, term, subject):
        self.calls.append(subject)
        return self.by_subject.get(subject, ())


class _Decider:
    name = "stub"

    def __init__(self, probabilities, error=None):
        self._probabilities, self._error, self.asked = probabilities, error, []

    def decide(self, state, questions):
        if self._error:
            raise self._error
        live = state["live_course"]["code"]
        self.asked.append(live)
        return {COURSE_EQUIVALENT: BooleanAnswer(probability=self._probabilities.get(live, 0.0))}


def _run(source, courses, lister, resolver=None, decider=None, known=frozenset()):
    return discover_aliases(source=source, term=_TERM, courses=courses, lister=lister,
                            resolver=resolver or CourseResolver(), decider=decider, known_pairs=known)


def test_exact_listing_hit_is_matched():
    (outcome,) = _run(_FRESNO, [AssistCourse("MATH 6", "Mathematical Analysis III", "MATH 32A")],
                      _Lister({"MATH": _CATALOG}))
    assert (outcome.status, outcome.aliases, outcome.note) == ("matched", (), "listed as MATH 6")


def test_formerly_note_gives_a_verified_alias_without_a_decider():
    (outcome,) = _run(_FRESNO, [AssistCourse("MATH 5B", "Mathematical Analysis II", "MATH 31B")],
                      _Lister({"MATH": _CATALOG}))
    assert outcome.status == "formerly"
    (alias,) = outcome.aliases
    assert (alias.old_code, alias.new_code, alias.status) == ("MATH 5B", "MATH C2220", "verified")


def test_renamed_subject_is_listed_and_rename_hit_is_matched():
    resolver = CourseResolver(renames=[SubjectRename(78, "MAT", "MATH", "rccd_live_listing")])
    lister = _Lister({"MATH": _RCC_MATH})
    (outcome,) = _run(_RIVERSIDE, [AssistCourse("MAT 1C", "Calculus III", "MATH 32A")], lister, resolver)
    assert outcome.status == "matched" and lister.calls == ["MAT", "MATH"]


def test_course_with_an_alias_elsewhere_is_matched():
    resolver = CourseResolver(aliases=[CourseAlias(78, "MAT 12", "STAT C1000", "rccd_crosswalk", "verified")])
    (outcome,) = _run(_RIVERSIDE, [AssistCourse("MAT 12", "Statistics", "STATS 10")], _Lister({}), resolver)
    assert outcome.status == "matched" and "already mapped" in outcome.note


def test_no_decider_and_no_title_are_reported():
    lister = _Lister({"MAT": _RCC_MATH})
    (no_decider,) = _run(_RIVERSIDE, [AssistCourse("MAT 1B", "Calculus II", "MATH 31B")], lister, decider=None)
    (no_title,) = _run(_RIVERSIDE, [AssistCourse("MAT 1A", "", "MATH 31A")], lister, decider=_Decider({}))
    assert no_decider.status == "needs_decider"
    assert no_title.status == "needs_title"


def test_no_decider_logs_a_warning(caplog):
    lister = _Lister({"MAT": _RCC_MATH})
    with caplog.at_level(logging.WARNING, logger="src.matching.discover"):
        _run(_RIVERSIDE, [AssistCourse("MAT 1B", "Calculus II", "MATH 31B")], lister, decider=None)
    assert "MAT 1B" in caplog.text and "needs_decider" in caplog.text.lower()


def test_decision_accepts_best_and_queues_or_rejects_the_rest():
    decider = _Decider({"MATH-C2220": 0.96, "MATH-C2210": 0.62, "MATH-1C": 0.05})
    (outcome,) = _run(_RIVERSIDE, [AssistCourse("MAT 1B", "Calculus II", "MATH 31B")],
                      _Lister({"MAT": _RCC_MATH}), decider=decider)
    assert outcome.status == "decided"
    assert decider.asked[0] == "MATH-C2220"  # highest title overlap is asked first
    statuses = {a.new_code: (a.status, a.confidence, a.source) for a in outcome.aliases}
    assert statuses == {
        "MATH-C2220": ("accepted", 0.96, "decision:stub"),
        "MATH-C2210": ("review", 0.62, "decision:stub"),
        "MATH-1C": ("rejected", 0.05, "decision:stub"),
    }


def test_known_pairs_are_not_asked_again():
    known = frozenset({(78, "MAT|1B", "MATH|C2220"), (78, "MAT|1B", "MATH|C2210"), (78, "MAT|1B", "MATH|1C")})
    (outcome,) = _run(_RIVERSIDE, [AssistCourse("MAT 1B", "Calculus II", "MATH 31B")],
                      _Lister({"MAT": _RCC_MATH}), decider=_Decider({}), known=known)
    assert outcome.status == "no_candidates"


def test_decider_failure_writes_nothing():
    (outcome,) = _run(_RIVERSIDE, [AssistCourse("MAT 1B", "Calculus II", "MATH 31B")],
                      _Lister({"MAT": _RCC_MATH}), decider=_Decider({}, error=DecisionUnavailable("rate limited")))
    assert (outcome.status, outcome.aliases, outcome.note) == ("decider_unavailable", (), "rate limited")


def test_decider_failure_logs_a_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="src.matching.discover"):
        (outcome,) = _run(_RIVERSIDE, [AssistCourse("MAT 1B", "Calculus II", "MATH 31B")],
                          _Lister({"MAT": _RCC_MATH}), decider=_Decider({}, error=DecisionUnavailable("rate limited")))
    assert "MAT 1B" in caplog.text and "rate limited" in caplog.text


def test_listing_unsupported_is_reported_for_every_course():
    class _NoListing:
        def list_subject(self, **kwargs):
            raise ListingUnsupported("system='wvm_static' cannot list a whole subject")

    outcomes = _run(_FRESNO, [AssistCourse("MATH 5A", "t", "u"), AssistCourse("MATH 5B", "t", "u")], _NoListing())
    assert [o.status for o in outcomes] == ["listing_unsupported", "listing_unsupported"]


def test_rank_candidates_orders_by_title_overlap_then_code():
    ranked = rank_candidates(AssistCourse("MAT 1B", "Calculus II", "x"), _RCC_MATH, cc_id=78, known_pairs=frozenset())
    assert [c.code for c in ranked] == ["MATH-C2220", "MATH-1C", "MATH-C2210"]


def test_two_candidates_above_accept_leave_the_second_for_review():
    course = AssistCourse("A 1", "t", "u")
    aliases = aliases_from_scores(5, course, ((ListedCourse("B 1", "b"), 0.97), (ListedCourse("C 1", "c"), 0.95)), "llm")
    assert [(a.new_code, a.status) for a in aliases] == [("B 1", "accepted"), ("C 1", "review")]
