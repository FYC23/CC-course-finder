"""ScheduleService runs each college's lookups on its own worker, streaming results."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
import requests

from src.assist.models import ArticulationRow, IngestRun
from src.assist.store import ensure_db, save_rows, save_run
from src.schedule.models import CourseAvailability
from src.schedule.service import ScheduleService
from src.schedule.term import TermNotListedError

SCHOOL = "University of California, Los Angeles"
MAJOR = "Computer Science"
EVC, SJCC, WVC = 2, 136, 80  # EVC and SJCC share one server; WVC is on its own
NAMES = {EVC: "Evergreen Valley College", SJCC: "San Jose City College", WVC: "West Valley College"}


def _seed(db_path: Path, courses: dict[int, list[str]]) -> None:
    ensure_db(db_path)
    run = IngestRun.create(target_school=SCHOOL, target_major=MAJOR,
                           agreements_seen=1, rows_written=1)
    save_run(db_path, run)
    save_rows(db_path, run.run_id, [
        ArticulationRow(
            target_school=SCHOOL, target_major=MAJOR, target_requirement="REQ",
            uc_equivalent="UC 1", cc_name=NAMES[cc_id], cc_id=cc_id, course_code=code,
            course_title="T", agreement_id="1", academic_year="2025-2026", source_url="/a/1",
        )
        for cc_id, codes in courses.items()
        for code in codes
    ])


def _found(source, term, course_code: str) -> CourseAvailability:
    return CourseAvailability(cc_id=source.cc_id, cc_name=source.cc_name, term=term.label,
                              course_code=course_code, offered=True, sections=[],
                              source_url="https://example.edu", raw_summary="fixture")


class _Provider:
    """Test double; each instance is created by the service's provider factory."""

    def __init__(self, on_search) -> None:
        self._on_search = on_search

    def supports_source(self, source) -> bool:
        return source.system in ("colleague_selfservice", "wvm_static")

    def search_course(self, *, source, term, course_code: str) -> CourseAvailability:
        self._on_search(self, source, course_code)
        return _found(source, term, course_code)


def _service(db_path: Path, on_search, **kwargs) -> ScheduleService:
    return ScheduleService(db_path=db_path, provider_factory=lambda: _Provider(on_search), **kwargs)


def _query(service: ScheduleService) -> list[CourseAvailability]:
    return service.query(target_school=SCHOOL, target_major=MAJOR, term_label="Summer 2026")


def test_colleges_are_looked_up_at_the_same_time(tmp_path: Path) -> None:
    db = tmp_path / "a.sqlite3"
    _seed(db, {EVC: ["MATH 1"], WVC: ["MATH 2"]})
    # Each college waits for the other at the barrier; one-at-a-time lookups would time out.
    barrier = threading.Barrier(2, timeout=5)

    out = _query(_service(db, lambda *_: barrier.wait()))

    assert [(a.cc_id, a.raw_summary) for a in out] == [(EVC, "fixture"), (WVC, "fixture")]


def test_each_college_gets_its_own_provider(tmp_path: Path) -> None:
    db = tmp_path / "a.sqlite3"
    _seed(db, {EVC: ["MATH 1", "MATH 2"], WVC: ["MATH 3"]})
    used: list[tuple[int, int]] = []

    _query(_service(db, lambda provider, source, _code: used.append((source.cc_id, id(provider)))))

    by_college = {cc_id: {pid for c, pid in used if c == cc_id} for cc_id in (EVC, WVC)}
    assert all(len(pids) == 1 for pids in by_college.values())
    assert by_college[EVC] != by_college[WVC]


def test_results_keep_college_then_course_order(tmp_path: Path) -> None:
    db = tmp_path / "a.sqlite3"
    _seed(db, {WVC: ["MATH 9", "CS 1"], EVC: ["MATH 1"]})

    out = _query(_service(db, lambda *_: None))

    assert [(a.cc_id, a.course_code) for a in out] == [(EVC, "MATH 1"), (WVC, "CS 1"), (WVC, "MATH 9")]


def test_iter_results_yields_each_college_as_it_finishes(tmp_path: Path) -> None:
    db = tmp_path / "a.sqlite3"
    _seed(db, {EVC: ["MATH 1"], WVC: ["MATH 2"]})
    evc_may_finish = threading.Event()

    def on_search(_provider, source, _code):
        if source.cc_id == EVC:
            assert evc_may_finish.wait(timeout=5)

    service = _service(db, on_search)
    plan = service.plan(target_school=SCHOOL, target_major=MAJOR, term_label="Summer 2026")
    results = service.iter_results(plan)

    first = next(results)
    evc_may_finish.set()
    second = next(results)

    assert (first.cc_id, second.cc_id) == (WVC, EVC)
    assert [a.raw_summary for a in second.availabilities] == ["fixture"]


def test_plan_groups_course_codes_by_college(tmp_path: Path) -> None:
    db = tmp_path / "a.sqlite3"
    _seed(db, {EVC: ["MATH 2", "MATH 1"], WVC: ["CS 1"]})

    plan = _service(db, lambda *_: None).plan(
        target_school=SCHOOL, target_major=MAJOR, term_label="Summer 2026")

    assert plan.term.label == "Summer 2026"
    assert [(c.source.cc_id, c.course_codes) for c in plan.colleges] == [
        (EVC, ("MATH 1", "MATH 2")), (WVC, ("CS 1",))]


def test_skips_rest_of_college_after_it_cannot_be_reached(tmp_path: Path) -> None:
    db = tmp_path / "a.sqlite3"
    _seed(db, {EVC: ["MATH 1", "MATH 2", "MATH 3"], WVC: ["CS 1"]})
    calls: list[tuple[int, str]] = []

    def on_search(_provider, source, code):
        calls.append((source.cc_id, code))
        if source.cc_id == EVC:
            raise requests.ConnectionError("connection refused")

    out = _query(_service(db, on_search))

    assert sorted(calls) == [(EVC, "MATH 1"), (WVC, "CS 1")]
    evc = [a for a in out if a.cc_id == EVC]
    assert [a.course_code for a in evc] == ["MATH 1", "MATH 2", "MATH 3"]
    assert all(a.offered is False for a in evc)
    assert evc[0].raw_summary == "[request_error type=ConnectionError]"
    assert all("skipped" in a.raw_summary for a in evc[1:])


def test_other_errors_do_not_skip_the_rest_of_the_college(tmp_path: Path) -> None:
    db = tmp_path / "a.sqlite3"
    _seed(db, {EVC: ["MATH 1", "MATH 2"]})
    calls: list[str] = []

    def on_search(_provider, _source, code):
        calls.append(code)
        if code == "MATH 1":
            raise requests.HTTPError("500 Server Error")

    out = _query(_service(db, on_search))

    assert calls == ["MATH 1", "MATH 2"]
    assert [a.offered for a in out] == [False, True]


def test_limits_simultaneous_lookups_on_one_server(tmp_path: Path) -> None:
    db = tmp_path / "a.sqlite3"
    _seed(db, {EVC: ["MATH 1", "MATH 2"], SJCC: ["MATH 3", "MATH 4"]})
    lock = threading.Lock()
    in_flight = {"now": 0, "max": 0}

    def on_search(*_):
        with lock:
            in_flight["now"] += 1
            in_flight["max"] = max(in_flight["max"], in_flight["now"])
        time.sleep(0.05)
        with lock:
            in_flight["now"] -= 1

    _query(_service(db, on_search, max_per_host=1))

    assert in_flight["max"] == 1


def test_shared_provider_instance_runs_one_college_at_a_time(tmp_path: Path) -> None:
    """A single provider instance keeps per-session state, so it is never used concurrently."""
    db = tmp_path / "a.sqlite3"
    _seed(db, {EVC: ["MATH 1"], WVC: ["MATH 2"]})
    lock = threading.Lock()
    in_flight = {"now": 0, "max": 0}

    def on_search(*_):
        with lock:
            in_flight["now"] += 1
            in_flight["max"] = max(in_flight["max"], in_flight["now"])
        time.sleep(0.05)
        with lock:
            in_flight["now"] -= 1

    ScheduleService(db_path=db, provider=_Provider(on_search)).query(
        target_school=SCHOOL, target_major=MAJOR, term_label="Summer 2026")

    assert in_flight["max"] == 1



@pytest.mark.parametrize("error,reason", [
    (requests.ConnectionError("refused"), "Couldn't reach the college's schedule server."),
    (requests.ConnectTimeout("slow connect"), "Couldn't reach the college's schedule server."),
    (requests.ReadTimeout("slow"), "The college's schedule server took too long to answer."),
    (requests.HTTPError("500 Server Error"), "The college's schedule server returned an error."),
    (TermNotListedError("Term 'Summer 2026' not found"), "Summer 2026 isn't listed on the college's schedule site."),
    (AttributeError("'NoneType' object has no attribute 'get'"), "Something went wrong reading the college's schedule."),
])
def test_failed_lookup_says_why_it_could_not_check(tmp_path: Path, error, reason) -> None:
    db = tmp_path / "a.sqlite3"
    _seed(db, {EVC: ["MATH 1"]})

    def on_search(*_):
        raise error

    [out] = _query(_service(db, on_search))

    assert out.lookup_error == reason
    assert out.offered is False


def test_skipped_courses_say_the_college_could_not_be_reached(tmp_path: Path) -> None:
    db = tmp_path / "a.sqlite3"
    _seed(db, {EVC: ["MATH 1", "MATH 2"]})

    def on_search(*_):
        raise requests.ConnectionError("refused")

    out = _query(_service(db, on_search))

    assert [a.lookup_error for a in out] == ["Couldn't reach the college's schedule server."] * 2


def test_successful_lookup_has_no_lookup_error(tmp_path: Path) -> None:
    db = tmp_path / "a.sqlite3"
    _seed(db, {EVC: ["MATH 1"]})

    [out] = _query(_service(db, lambda *_: None))

    assert out.lookup_error is None


from src.schedule.errors import PortalChanged  # noqa: E402
from src.schedule.service import _lookup_error_reason  # noqa: E402
from src.schedule.term import parse_term_label as _parse_term  # noqa: E402


def test_portal_changed_has_a_student_facing_reason() -> None:
    reason = _lookup_error_reason(PortalChanged("rows path not found"), _parse_term("Fall 2026"))
    assert reason == "The college's schedule site changed; this lookup needs to be re-recorded."
    assert "rows path" not in reason


def test_spec_unavailable_has_a_student_facing_reason() -> None:
    from src.schedule.errors import SpecUnavailable

    reason = _lookup_error_reason(SpecUnavailable("no replay spec loaded for cc_id=78"), _parse_term("Fall 2026"))
    assert reason == "This college's schedule lookup is unavailable right now."
    assert "cc_id" not in reason
