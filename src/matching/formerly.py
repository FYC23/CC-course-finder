"""Catalog "formerly" notes: deterministic old-to-new code statements in course descriptions.

Two shapes appear (Fresno City, 2026-09-23):
  "... process. (Formerly MATH 5B) ..."            -> the described course was MATH 5B
  "Corequisite: STAT C1000 (formerly MATH 11) ..." -> STAT C1000 was MATH 11
Misspellings like "Fomerly" occur, so the word is matched loosely; codes must look like codes.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from src.schedule.listing import ListedCourse

from .models import CourseAlias

SOURCE = "catalog_formerly"
_CODE = r"[A-Z]{2,8}[ -]?C?\d{1,4}[A-Z]{0,2}"
_FORMERLY = r"(?i:fo\w*erly)"
_PAIRED_RE = re.compile(rf"(?P<new>{_CODE})\s*\(\s*{_FORMERLY}\s+(?P<old>{_CODE})\s*\)")
_BARE_RE = re.compile(rf"\(\s*{_FORMERLY}\s+(?P<old>{_CODE})\s*\)")


def formerly_pairs(course: ListedCourse) -> tuple[tuple[str, str, str], ...]:
    """(old code, new code, the matched text) for each note in the description."""
    text = course.description
    paired = list(_PAIRED_RE.finditer(text))
    pairs = [(m["old"], m["new"], m.group(0)) for m in paired]
    for match in _BARE_RE.finditer(text):
        if not any(p.start() <= match.start() < p.end() for p in paired):
            pairs.append((match["old"], course.code, match.group(0)))
    return tuple(pairs)


def formerly_aliases(cc_id: int, listed: Iterable[ListedCourse]) -> tuple[CourseAlias, ...]:
    found: dict[tuple[str, str], CourseAlias] = {}
    for course in listed:
        for old, new, evidence in formerly_pairs(course):
            alias = CourseAlias(
                cc_id=cc_id, old_code=old, new_code=new, source=SOURCE, status="verified",
                confidence=1.0, evidence=f"{course.code} catalog: {evidence}",
            )
            found.setdefault((alias.old_key, alias.new_key), alias)
    return tuple(found.values())
