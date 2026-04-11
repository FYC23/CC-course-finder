from __future__ import annotations

import sqlite3
from pathlib import Path

from .catalog import get_college_source
from .models import CourseAvailability
from .providers import ScheduleProvider
from .term import parse_term_label


class ScheduleService:
    def __init__(self, db_path: Path, provider: ScheduleProvider) -> None:
        self._db_path = db_path
        self._provider = provider

    def query(
        self,
        *,
        target_school: str,
        target_major: str,
        term_label: str,
        cc_id: int | None = None,
        requirement_filter: str | None = None,
    ) -> list[CourseAvailability]:
        term = parse_term_label(term_label)
        if cc_id is not None:
            get_college_source(cc_id)
        course_keys = self._select_candidate_course_keys(
            target_school=target_school,
            target_major=target_major,
            cc_id=cc_id,
            requirement_filter=requirement_filter,
        )
        results: list[CourseAvailability] = []
        for row_cc_id, course_code in course_keys:
            try:
                source = get_college_source(row_cc_id)
            except KeyError:
                continue
            results.append(
                self._provider.search_course(
                    source=source, term=term, course_code=course_code
                )
            )
        return results

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
