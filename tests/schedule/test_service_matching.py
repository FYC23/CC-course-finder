"""ScheduleService looks each ASSIST course up under every live code the resolver gives."""
from __future__ import annotations

from pathlib import Path

from src.assist.models import ArticulationRow, IngestRun
from src.assist.store import ensure_db, save_rows, save_run
from src.matching.models import CourseAlias
from src.matching.resolve import CourseResolver
from src.schedule.models import CourseAvailability, ParsedSection
from src.schedule.service import ScheduleService

SCHOOL, MAJOR = "University of California, Los Angeles", "Computer Science"


def _seed(db: Path, cc_id: int, cc_name: str, code: str) -> None:
    ensure_db(db)
    run = IngestRun.create(target_school=SCHOOL, target_major=MAJOR, agreements_seen=1, rows_written=1)
    save_run(db, run)
    save_rows(db, run.run_id, [ArticulationRow(
        target_school=SCHOOL, target_major=MAJOR, target_requirement="MATH 31B", uc_equivalent="MATH 31B",
        cc_name=cc_name, cc_id=cc_id, course_code=code, course_title="Calculus II", agreement_id="1",
        academic_year="2025-2026", source_url="/a/1",
    )])


class _Provider:
    def __init__(self, calls: list[str], offered: set[str]) -> None:
        self._calls, self._offered = calls, offered

    def supports_source(self, source) -> bool:
        return True

    def search_course(self, *, source, term, course_code: str) -> CourseAvailability:
        self._calls.append(course_code)
        sections = ([ParsedSection(section_id="1", status="open", modality="unknown", title="t",
                                   instructor="", course_code_as_listed=course_code)]
                    if course_code in self._offered else [])
        return CourseAvailability(cc_id=source.cc_id, cc_name=source.cc_name, term=term.label,
                                  course_code=course_code, offered=bool(sections), sections=sections,
                                  source_url="https://x.test", raw_summary="r")


def _service(db, calls, offered, resolver=None):
    kwargs = {"resolver_loader": (lambda _db: resolver)} if resolver is not None else {}
    return ScheduleService(db_path=db, provider_factory=lambda: _Provider(calls, offered), **kwargs)


def test_alias_lookup_turns_not_offered_into_offered(tmp_path: Path):
    db = tmp_path / "a.sqlite3"
    _seed(db, 35, "Fresno City College", "MATH 5A")
    resolver = CourseResolver(aliases=[CourseAlias(cc_id=35, old_code="MATH 5A", new_code="MATH C2210",
                                                   source="catalog_formerly", status="verified")])
    calls: list[str] = []
    (result,) = _service(db, calls, {"MATH C2210"}, resolver).query(
        target_school=SCHOOL, target_major=MAJOR, term_label="Fall 2026")
    assert calls == ["MATH C2210", "MATH 5A"]
    assert (result.course_code, result.offered, result.matched_code) == ("MATH 5A", True, "MATH C2210")


def test_plan_carries_live_codes(tmp_path: Path):
    db = tmp_path / "a.sqlite3"
    _seed(db, 35, "Fresno City College", "MATH 5A")
    resolver = CourseResolver(aliases=[CourseAlias(cc_id=35, old_code="MATH 5A", new_code="MATH C2210",
                                                   source="s", status="verified")])
    plan = _service(db, [], set(), resolver).plan(target_school=SCHOOL, target_major=MAJOR, term_label="Fall 2026")
    (college,) = plan.colleges
    assert [c.code for c in college.lookups_for("MATH 5A")] == ["MATH C2210", "MATH 5A"]
    assert [c.code for c in college.lookups_for("OTHER 1")] == ["OTHER 1"]


def test_default_resolver_reads_committed_seeds(tmp_path: Path):
    db = tmp_path / "a.sqlite3"
    _seed(db, 78, "Riverside City College", "MAT 1B")
    calls: list[str] = []
    (result,) = _service(db, calls, {"MATH-C2220"}).query(
        target_school=SCHOOL, target_major=MAJOR, term_label="Fall 2026")
    assert calls == ["MATH-C2220", "MATH 1B", "MAT 1B"]
    assert (result.offered, result.match_source) == (True, "rccd_crosswalk")
