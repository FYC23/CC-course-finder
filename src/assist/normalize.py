from __future__ import annotations

from .models import ArticulationRow


def dedupe_rows(rows: list[ArticulationRow]) -> list[ArticulationRow]:
    seen: set[tuple[int, str, str, int]] = set()
    unique: list[ArticulationRow] = []
    for row in rows:
        key = (row.cc_id, row.course_code, row.uc_equivalent, row.agreement_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def filter_empty_course_codes(rows: list[ArticulationRow]) -> list[ArticulationRow]:
    return [row for row in rows if row.course_code.strip()]

