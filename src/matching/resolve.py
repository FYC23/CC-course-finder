"""Map an ASSIST course code to the codes to look it up under this term (spec 9.2 step 1).

Deterministic and offline: committed seeds plus the SQLite alias table, read once per
search. No network, no model. The last lookup slot is always reserved for the ASSIST
code itself, so a wrong alias can never crowd out a course still listed under its old
code.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .codes import code_key, split_code, subject_key
from .models import ACTIVE_STATUSES, CourseAlias, SubjectRename
from .seeds import SeedInvalid, load_seed_aliases, load_subject_renames
from .store import list_aliases

logger = logging.getLogger(__name__)

MAX_LOOKUPS_PER_COURSE = 3
_STATUS_ORDER = {"verified": 0, "accepted": 1}


@dataclass(frozen=True)
class LiveCode:
    """One code to look a course up under. ``source`` and ``status`` are empty for the
    ASSIST code itself and name the alias or subject rename otherwise."""

    code: str
    source: str = ""
    status: str = ""

    @property
    def is_alias(self) -> bool:
        return bool(self.source)


def _pair(alias: CourseAlias) -> tuple[int, str, str]:
    return alias.cc_id, alias.old_key, alias.new_key


def _alias_order(alias: CourseAlias) -> tuple[int, float, str]:
    return _STATUS_ORDER[alias.status], -alias.confidence, alias.new_code


def _unique(codes: Iterable[LiveCode]) -> tuple[LiveCode, ...]:
    seen: set[str] = set()
    kept: list[LiveCode] = []
    for live in codes:
        key = code_key(live.code)
        if key not in seen:
            seen.add(key)
            kept.append(live)
    return tuple(kept)


class CourseResolver:
    def __init__(
        self,
        aliases: Iterable[CourseAlias] = (),
        renames: Iterable[SubjectRename] = (),
        blocked: Iterable[CourseAlias] = (),
    ) -> None:
        blocked_pairs = frozenset(_pair(alias) for alias in blocked)
        by_old: dict[tuple[int, str], list[CourseAlias]] = {}
        for alias in aliases:
            if alias.status in ACTIVE_STATUSES and _pair(alias) not in blocked_pairs:
                by_old.setdefault((alias.cc_id, alias.old_key), []).append(alias)
        self._aliases = MappingProxyType(
            {key: tuple(sorted(group, key=_alias_order)) for key, group in by_old.items()}
        )
        by_subject: dict[tuple[int, str], list[SubjectRename]] = {}
        for rename in renames:
            by_subject.setdefault((rename.cc_id, subject_key(rename.old_subject)), []).append(rename)
        self._renames = MappingProxyType({key: tuple(group) for key, group in by_subject.items()})

    def live_codes(self, cc_id: int, course_code: str) -> tuple[LiveCode, ...]:
        candidates: list[LiveCode] = []
        for spelling, rename in self._spellings(cc_id, course_code):
            for alias in self._aliases.get((cc_id, code_key(spelling)), ()):
                candidates.append(LiveCode(alias.new_code, alias.source, alias.status))
            if rename is not None:
                candidates.append(LiveCode(spelling, rename.source, "verified"))
        assist_key = code_key(course_code)
        non_assist = tuple(c for c in _unique(candidates) if code_key(c.code) != assist_key)
        return non_assist[: MAX_LOOKUPS_PER_COURSE - 1] + (LiveCode(course_code),)

    def has_alias(self, cc_id: int, course_code: str) -> bool:
        """True when a course-level alias exists for the code or one of its renamed spellings."""
        return any(
            self._aliases.get((cc_id, code_key(spelling)))
            for spelling, _ in self._spellings(cc_id, course_code)
        )

    def renamed_subjects(self, cc_id: int, subject: str) -> tuple[str, ...]:
        return tuple(r.new_subject for r in self._renames.get((cc_id, subject_key(subject)), ()))

    def _spellings(self, cc_id: int, course_code: str) -> list[tuple[str, SubjectRename | None]]:
        spellings: list[tuple[str, SubjectRename | None]] = [(course_code, None)]
        parts = split_code(course_code)
        if parts is not None:
            subject, number = parts
            for rename in self._renames.get((cc_id, subject_key(subject)), ()):
                spellings.append((f"{rename.new_subject} {number}", rename))
        return spellings


def load_resolver(db_path: Path) -> CourseResolver:
    """Committed seeds plus the database. A human rejection in the database blocks the
    same pair everywhere; an automated rejection does not override a seed."""
    stored = list_aliases(db_path)
    try:
        seeds, renames = load_seed_aliases(), load_subject_renames()
    except (SeedInvalid, OSError):
        logger.exception("course alias seed files are invalid; matching uses database aliases only")
        seeds, renames = (), ()
    blocked = tuple(a for a in stored if a.status == "rejected" and a.reviewed)
    return CourseResolver(aliases=(*seeds, *stored), renames=renames, blocked=blocked)
