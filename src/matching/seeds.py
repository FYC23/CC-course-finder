"""Committed, verified course mappings under src/matching/data/.

These files travel with the code (data/assist.sqlite3 does not), so a fresh clone matches
renumbered courses without any setup. ``cc_ids`` is a space-separated list because a
district-wide crosswalk applies to every college in the district.
"""
from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from pathlib import Path

from .codes import split_code
from .models import CourseAlias, SubjectRename

SEED_DIR = Path(__file__).parent / "data"
ALIASES_FILE = SEED_DIR / "course_aliases.csv"
RENAMES_FILE = SEED_DIR / "subject_renames.csv"
_ALIAS_HEADER = ("cc_ids", "old_code", "new_code", "source", "evidence")
_RENAME_HEADER = ("cc_ids", "old_subject", "new_subject", "source", "evidence")
_SUBJECT_RE = re.compile(r"^[A-Za-z][A-Za-z&/. ]*$")


class SeedInvalid(ValueError):
    """A committed seed file is malformed. The message names the file and line."""


def _rows(path: Path, header: tuple[str, ...]) -> Iterator[tuple[int, dict[str, str]]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != header:
            raise SeedInvalid(f"{path.name}: header must be {','.join(header)}")
        for row in reader:
            yield reader.line_num, {key: (value or "").strip() for key, value in row.items()}


def _cc_ids(where: str, raw: str) -> tuple[int, ...]:
    try:
        ids = tuple(int(part) for part in raw.split())
    except ValueError:
        raise SeedInvalid(f"{where}: cc_ids must be space-separated integers, got {raw!r}") from None
    if not ids:
        raise SeedInvalid(f"{where}: cc_ids is empty")
    return ids


def _check_source(where: str, row: dict[str, str]) -> None:
    if not row["source"]:
        raise SeedInvalid(f"{where}: source is empty")


def _aliases(where: str, row: dict[str, str]) -> tuple[CourseAlias, ...]:
    for name in ("old_code", "new_code"):
        if split_code(row[name]) is None:
            raise SeedInvalid(f"{where}: {name} {row[name]!r} is not a course code")
    _check_source(where, row)
    return tuple(
        CourseAlias(
            cc_id=cc_id, old_code=row["old_code"], new_code=row["new_code"], source=row["source"],
            status="verified", confidence=1.0, evidence=row["evidence"],
        )
        for cc_id in _cc_ids(where, row["cc_ids"])
    )


def _renames(where: str, row: dict[str, str]) -> tuple[SubjectRename, ...]:
    for name in ("old_subject", "new_subject"):
        if not _SUBJECT_RE.match(row[name]):
            raise SeedInvalid(f"{where}: {name} {row[name]!r} is not a subject")
    _check_source(where, row)
    return tuple(
        SubjectRename(
            cc_id=cc_id, old_subject=row["old_subject"].upper(), new_subject=row["new_subject"].upper(),
            source=row["source"], evidence=row["evidence"],
        )
        for cc_id in _cc_ids(where, row["cc_ids"])
    )


def load_seed_aliases(path: Path = ALIASES_FILE) -> tuple[CourseAlias, ...]:
    return tuple(
        alias for line, row in _rows(path, _ALIAS_HEADER) for alias in _aliases(f"{path.name}:{line}", row)
    )


def load_subject_renames(path: Path = RENAMES_FILE) -> tuple[SubjectRename, ...]:
    return tuple(
        rename for line, row in _rows(path, _RENAME_HEADER) for rename in _renames(f"{path.name}:{line}", row)
    )
