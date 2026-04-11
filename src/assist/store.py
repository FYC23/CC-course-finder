from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import ArticulationRow, IngestRun


def ensure_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ingest_runs (
                run_id TEXT PRIMARY KEY,
                created_at_utc TEXT NOT NULL,
                target_school TEXT NOT NULL,
                target_major TEXT NOT NULL,
                agreements_seen INTEGER NOT NULL,
                rows_written INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS articulation_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                target_school TEXT NOT NULL,
                target_major TEXT NOT NULL,
                target_requirement TEXT NOT NULL,
                uc_equivalent TEXT NOT NULL,
                cc_name TEXT NOT NULL,
                cc_id INTEGER NOT NULL,
                course_code TEXT NOT NULL,
                course_title TEXT NOT NULL,
                agreement_id TEXT NOT NULL,
                academic_year TEXT NOT NULL,
                source_url TEXT NOT NULL,
                notes TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                UNIQUE (run_id, cc_id, course_code, uc_equivalent, agreement_id)
            )
            """
        )


def save_run(path: Path, run: IngestRun) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO ingest_runs (
                run_id, created_at_utc, target_school, target_major, agreements_seen, rows_written
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.created_at_utc,
                run.target_school,
                run.target_major,
                run.agreements_seen,
                run.rows_written,
            ),
        )


def save_rows(path: Path, run_id: str, rows: list[ArticulationRow]) -> int:
    inserted = 0
    with sqlite3.connect(path) as conn:
        for row in rows:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO articulation_rows (
                    run_id, target_school, target_major, target_requirement, uc_equivalent,
                    cc_name, cc_id, course_code, course_title, agreement_id,
                    academic_year, source_url, notes, raw_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    row.target_school,
                    row.target_major,
                    row.target_requirement,
                    row.uc_equivalent,
                    row.cc_name,
                    row.cc_id,
                    row.course_code,
                    row.course_title,
                    row.agreement_id,
                    row.academic_year,
                    row.source_url,
                    row.notes,
                    row.raw_text,
                ),
            )
            inserted += int(cursor.rowcount > 0)
    return inserted


def query_rows(
    path: Path,
    target_school: str,
    target_major: str,
    requirement_filter: str | None = None,
) -> list[ArticulationRow]:
    sql = """
        SELECT
            target_school, target_major, target_requirement, uc_equivalent,
            cc_name, cc_id, course_code, course_title, agreement_id, academic_year,
            source_url, notes, raw_text
        FROM articulation_rows
        WHERE target_school = ? AND target_major = ?
    """
    params: list[object] = [target_school, target_major]
    if requirement_filter:
        sql += " AND (target_requirement LIKE ? OR uc_equivalent LIKE ?)"
        like = f"%{requirement_filter}%"
        params.extend([like, like])
    sql += " ORDER BY cc_name ASC, course_code ASC"

    with sqlite3.connect(path) as conn:
        records = conn.execute(sql, params).fetchall()

    return [
        ArticulationRow(
            target_school=r[0],
            target_major=r[1],
            target_requirement=r[2],
            uc_equivalent=r[3],
            cc_name=r[4],
            cc_id=int(r[5]),
            course_code=r[6],
            course_title=r[7],
            agreement_id=str(r[8]),
            academic_year=r[9],
            source_url=r[10],
            notes=r[11],
            raw_text=r[12],
        )
        for r in records
    ]

