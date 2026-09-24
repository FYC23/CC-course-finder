from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .catalog import get_college_source
from .models import CollegeScheduleSource, CourseAvailability
from .providers import ScheduleProvider
from .term import ParsedTerm, TermNotListedError, parse_term_label

logger = logging.getLogger(__name__)

# Colleges looked up at once. Each college's own courses still go one at a time.
DEFAULT_MAX_WORKERS = 16
# Lookups one schedule server gets at once; a few servers host 2-3 colleges.
DEFAULT_MAX_PER_HOST = 3


@dataclass(frozen=True)
class CollegeLookups:
    source: CollegeScheduleSource
    course_codes: tuple[str, ...]


@dataclass(frozen=True)
class QueryPlan:
    term: ParsedTerm
    colleges: tuple[CollegeLookups, ...]


@dataclass(frozen=True)
class CollegeResult:
    cc_id: int
    availabilities: tuple[CourseAvailability, ...]


class ScheduleService:
    """Looks up ASSIST-articulated courses in each college's live schedule.

    Pass ``provider_factory`` to look colleges up in parallel: every college gets its own
    provider (and so its own HTTP session, since Banner keeps the chosen term server-side
    per session). A single shared ``provider`` instance is used one college at a time.
    """

    def __init__(
        self,
        db_path: Path,
        provider: ScheduleProvider | None = None,
        *,
        provider_factory: Callable[[], ScheduleProvider] | None = None,
        max_workers: int = DEFAULT_MAX_WORKERS,
        max_per_host: int = DEFAULT_MAX_PER_HOST,
    ) -> None:
        if (provider is None) == (provider_factory is None):
            raise ValueError("Pass exactly one of provider or provider_factory")
        self._db_path = db_path
        if provider is not None:
            self._provider_factory: Callable[[], ScheduleProvider] = lambda: provider
            self._max_workers = 1
        else:
            self._provider_factory = provider_factory  # type: ignore[assignment]
            self._max_workers = max(1, max_workers)
        self._max_per_host = max(1, max_per_host)
        self._host_limits: dict[str, threading.BoundedSemaphore] = {}
        self._host_limits_lock = threading.Lock()

    def query(
        self,
        *,
        target_school: str,
        target_major: str,
        term_label: str,
        cc_id: int | None = None,
        requirement_filter: str | None = None,
    ) -> list[CourseAvailability]:
        plan = self.plan(
            target_school=target_school,
            target_major=target_major,
            term_label=term_label,
            cc_id=cc_id,
            requirement_filter=requirement_filter,
        )
        by_college = {r.cc_id: r.availabilities for r in self.iter_results(plan)}
        return [a for college in plan.colleges for a in by_college[college.source.cc_id]]

    def plan(
        self,
        *,
        target_school: str,
        target_major: str,
        term_label: str,
        cc_id: int | None = None,
        requirement_filter: str | None = None,
    ) -> QueryPlan:
        """Decide which colleges and courses to look up. Raises ValueError up front for a
        bad term or a college whose schedule system has no provider."""
        term = parse_term_label(term_label)
        if cc_id is not None:
            get_college_source(cc_id)
        course_keys = self._select_candidate_course_keys(
            target_school=target_school,
            target_major=target_major,
            cc_id=cc_id,
            requirement_filter=requirement_filter,
        )
        checker = self._provider_factory()
        colleges: list[CollegeLookups] = []
        for row_cc_id, keys in groupby(course_keys, key=lambda key: key[0]):
            try:
                source = get_college_source(row_cc_id)
            except KeyError:
                continue
            if source.status == "unsupported":
                continue
            if not checker.supports_source(source):
                raise ValueError(
                    f"No provider configured for source system={source.system!r} "
                    f"(cc_id={source.cc_id}, cc_name={source.cc_name})"
                )
            codes = tuple(dict.fromkeys(code for _, code in keys))
            colleges.append(CollegeLookups(source=source, course_codes=codes))
        return QueryPlan(term=term, colleges=tuple(colleges))

    def iter_results(self, plan: QueryPlan) -> Iterator[CollegeResult]:
        """Yield each college's results as soon as that college is done.

        Closing the iterator early (e.g. the browser went away) stops colleges that have
        not started and makes running ones stop after their current lookup.
        """
        if not plan.colleges:
            return
        cancelled = threading.Event()
        executor = ThreadPoolExecutor(
            max_workers=min(self._max_workers, len(plan.colleges)),
            thread_name_prefix="schedule-lookup",
        )
        try:
            pending: set[Future[CollegeResult]] = {
                executor.submit(self._lookup_college, college, plan.term, cancelled)
                for college in plan.colleges
            }
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    yield future.result()
        finally:
            cancelled.set()
            executor.shutdown(wait=False, cancel_futures=True)

    def _lookup_college(
        self, college: CollegeLookups, term: ParsedTerm, cancelled: threading.Event
    ) -> CollegeResult:
        source = college.source
        provider = self._provider_factory()
        host_limit = self._host_limit(source.base_url)
        results: list[CourseAvailability] = []
        unreachable: requests.ConnectionError | None = None
        for course_code in college.course_codes:
            if cancelled.is_set():
                break
            if unreachable is not None:
                results.append(_failed(source, term, course_code, unreachable, skipped=True))
                continue
            try:
                with host_limit:
                    availability = provider.search_course(
                        source=source, term=term, course_code=course_code
                    )
            except Exception as err:
                logger.exception(
                    "Schedule lookup failed for cc_id=%s course_code=%r",
                    source.cc_id,
                    course_code,
                )
                if isinstance(err, requests.ConnectionError):
                    # The server is down or refusing us; every other course would just
                    # wait out the same failure.
                    unreachable = err
                availability = _failed(source, term, course_code, err, skipped=False)
            results.append(availability)
        return CollegeResult(cc_id=source.cc_id, availabilities=tuple(results))

    def _host_limit(self, base_url: str) -> threading.BoundedSemaphore:
        host = urlsplit(base_url).netloc.lower()
        with self._host_limits_lock:
            if host not in self._host_limits:
                self._host_limits[host] = threading.BoundedSemaphore(self._max_per_host)
            return self._host_limits[host]

    def _select_candidate_course_keys(
        self,
        *,
        target_school: str,
        target_major: str,
        cc_id: int | None,
        requirement_filter: str | None,
    ) -> list[tuple[int, str]]:
        sql = """
            SELECT DISTINCT cc_id, course_code
            FROM articulation_rows
            WHERE target_school = ? AND target_major = ?
        """
        params: list[object] = [target_school, target_major]
        if cc_id is not None:
            sql += " AND cc_id = ?"
            params.append(cc_id)
        if requirement_filter:
            sql += " AND (target_requirement LIKE ? OR uc_equivalent LIKE ?)"
            like = f"%{requirement_filter}%"
            params.extend([like, like])
        sql += " ORDER BY cc_id ASC, course_code ASC"

        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [(int(row[0]), str(row[1])) for row in rows]


def _failed(
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
        lookup_error=_lookup_error_reason(err, term),
    )


def _lookup_error_reason(err: Exception, term: ParsedTerm) -> str:
    """A student-facing reason the course could not be checked (no internals leaked)."""
    if isinstance(err, requests.ConnectionError):
        return "Couldn't reach the college's schedule server."
    if isinstance(err, requests.Timeout):
        return "The college's schedule server took too long to answer."
    if isinstance(err, requests.HTTPError):
        return "The college's schedule server returned an error."
    if isinstance(err, TermNotListedError):
        return f"{term.label} isn't listed on the college's schedule site."
    return "Something went wrong reading the college's schedule."
