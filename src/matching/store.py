"""SQLite table of course aliases found by `matching discover` or added by hand.

Lives in data/assist.sqlite3 next to the ASSIST rows. Committed seeds (seeds.py) are not
copied here; the resolver reads both. A row a human reviewed is never overwritten by a
later automated pass, and an automated pass never downgrades a row's status.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Collection
from pathlib import Path

from src.assist.store import _connect, _utc_now, _with_write_retry  # shared helpers for this DB file

from .models import CourseAlias

_STATUS_RANK = {"rejected": 0, "review": 1, "accepted": 2, "verified": 3}
_SELECT = (
    "SELECT alias_id, cc_id, old_code, new_code, source, confidence, status, evidence, reviewed "
    "FROM course_aliases"
)


def ensure_alias_table(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS course_aliases (
                alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
                cc_id INTEGER NOT NULL,
                old_code TEXT NOT NULL,
                old_key TEXT NOT NULL,
                new_code TEXT NOT NULL,
                new_key TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('verified', 'accepted', 'review', 'rejected')),
                evidence TEXT NOT NULL DEFAULT '',
                reviewed INTEGER NOT NULL DEFAULT 0,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                reviewed_at_utc TEXT,
                UNIQUE (cc_id, old_key, new_key)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_course_aliases_cc ON course_aliases (cc_id)")


def _to_alias(row: tuple) -> CourseAlias:
    alias_id, cc_id, old_code, new_code, source, confidence, status, evidence, reviewed = row
    return CourseAlias(
        cc_id=int(cc_id), old_code=old_code, new_code=new_code, source=source, status=status,
        confidence=float(confidence), evidence=evidence, alias_id=int(alias_id), reviewed=bool(reviewed),
    )


def upsert_alias(path: Path, alias: CourseAlias) -> str:
    ensure_alias_table(path)

    def write(conn: sqlite3.Connection) -> str:
        key = (alias.cc_id, alias.old_key, alias.new_key)
        existing = conn.execute(
            "SELECT status, reviewed FROM course_aliases WHERE cc_id = ? AND old_key = ? AND new_key = ?",
            key,
        ).fetchone()
        now = _utc_now()
        reviewed_at = now if alias.reviewed else None
        if existing is None:
            conn.execute(
                """
                INSERT INTO course_aliases (cc_id, old_code, old_key, new_code, new_key, source,
                    confidence, status, evidence, reviewed, created_at_utc, updated_at_utc, reviewed_at_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (alias.cc_id, alias.old_code, alias.old_key, alias.new_code, alias.new_key, alias.source,
                 alias.confidence, alias.status, alias.evidence, int(alias.reviewed), now, now, reviewed_at),
            )
            return "inserted"
        status, reviewed = existing
        if not alias.reviewed and (reviewed or _STATUS_RANK[status] > _STATUS_RANK[alias.status]):
            return "kept"
        conn.execute(
            """
            UPDATE course_aliases SET old_code = ?, new_code = ?, source = ?, confidence = ?, status = ?,
                evidence = ?, reviewed = ?, updated_at_utc = ?, reviewed_at_utc = COALESCE(?, reviewed_at_utc)
            WHERE cc_id = ? AND old_key = ? AND new_key = ?
            """,
            (alias.old_code, alias.new_code, alias.source, alias.confidence, alias.status, alias.evidence,
             int(alias.reviewed or reviewed), now, reviewed_at, *key),
        )
        return "updated"

    return _with_write_retry(path, write)


def list_aliases(
    path: Path, *, cc_id: int | None = None, statuses: Collection[str] | None = None
) -> tuple[CourseAlias, ...]:
    if not path.exists():
        return ()
    sql = f"{_SELECT} WHERE 1 = 1"
    params: list[object] = []
    if cc_id is not None:
        sql += " AND cc_id = ?"
        params.append(cc_id)
    if statuses:
        sql += f" AND status IN ({', '.join('?' for _ in statuses)})"
        params.extend(statuses)
    sql += " ORDER BY cc_id, old_key, confidence DESC, alias_id"
    try:
        with _connect(path) as conn:
            rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as err:
        if "no such table" in str(err).lower():
            return ()
        raise
    return tuple(_to_alias(row) for row in rows)


def get_alias(path: Path, alias_id: int) -> CourseAlias:
    with _connect(path) as conn:
        row = conn.execute(f"{_SELECT} WHERE alias_id = ?", (alias_id,)).fetchone()
    if row is None:
        raise KeyError(f"no alias with id {alias_id}")
    return _to_alias(row)


def review_alias(path: Path, alias_id: int, *, approve: bool) -> CourseAlias:
    ensure_alias_table(path)

    def write(conn: sqlite3.Connection) -> int:
        now = _utc_now()
        cursor = conn.execute(
            """
            UPDATE course_aliases SET status = ?, reviewed = 1, reviewed_at_utc = ?, updated_at_utc = ?
            WHERE alias_id = ?
            """,
            ("verified" if approve else "rejected", now, now, alias_id),
        )
        return cursor.rowcount

    if _with_write_retry(path, write) == 0:
        raise KeyError(f"no alias with id {alias_id}")
    return get_alias(path, alias_id)
