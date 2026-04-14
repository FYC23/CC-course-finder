from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DB_PATH
from .models import ArticulationRow, IngestRun


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


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
                rows_written INTEGER NOT NULL,
                max_cc INTEGER,
                allow_non_numeric_keys INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        # Backward-compatible migration for existing DBs.
        for column, dtype in [
            ("max_cc", "INTEGER"),
            ("allow_non_numeric_keys", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE ingest_runs ADD COLUMN {column} {dtype}")
            except sqlite3.OperationalError:
                pass
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
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_artic_school_major
                ON articulation_rows (target_school, target_major)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ingest_jobs (
                job_id TEXT PRIMARY KEY,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                target_school TEXT NOT NULL,
                target_major TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                started_at_utc TEXT,
                completed_at_utc TEXT,
                run_id TEXT,
                rows_written INTEGER DEFAULT 0,
                agreements_seen INTEGER DEFAULT 0,
                error_message TEXT,
                max_cc INTEGER,
                allow_non_numeric_keys INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_school_major_status
                ON ingest_jobs (target_school, target_major, status)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ingest_freshness (
                target_school TEXT NOT NULL,
                target_major TEXT NOT NULL,
                options_hash TEXT NOT NULL,
                last_successful_run_id TEXT,
                ingested_at_utc TEXT NOT NULL,
                agreements_seen INTEGER DEFAULT 0,
                rows_written INTEGER DEFAULT 0,
                PRIMARY KEY (target_school, target_major, options_hash)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_freshness_school_major
                ON ingest_freshness (target_school, target_major)
            """
        )


def save_run(path: Path, run: IngestRun) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO ingest_runs (
                run_id, created_at_utc, target_school, target_major, agreements_seen, rows_written,
                max_cc, allow_non_numeric_keys
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.created_at_utc,
                run.target_school,
                run.target_major,
                run.agreements_seen,
                run.rows_written,
                getattr(run, "max_cc", None),
                int(bool(getattr(run, "allow_non_numeric_keys", False))),
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


def compute_options_hash(max_cc: int | None, allow_non_numeric_keys: bool) -> str:
    return hashlib.sha256(
        f"{max_cc}:{int(allow_non_numeric_keys)}".encode()
    ).hexdigest()[:8]


def has_rows_for(path: Path, school: str, major: str) -> bool:
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM articulation_rows
            WHERE target_school = ? AND target_major = ?
            LIMIT 1
            """,
            (school, major),
        ).fetchone()
    return row is not None


def create_job(
    path: Path,
    job_id: str,
    school: str,
    major: str,
    max_cc: int | None,
    allow_non_numeric_keys: bool,
) -> None:
    now = _utc_now()
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO ingest_jobs (
                job_id, created_at_utc, updated_at_utc, target_school, target_major,
                status, max_cc, allow_non_numeric_keys
            ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                job_id,
                now,
                now,
                school,
                major,
                max_cc,
                int(allow_non_numeric_keys),
            ),
        )


def update_job(path: Path, job_id: str, **fields: Any) -> None:
    allowed = {
        "status",
        "started_at_utc",
        "completed_at_utc",
        "run_id",
        "rows_written",
        "agreements_seen",
        "error_message",
    }
    updates = [f"{key}=?" for key in fields if key in allowed]
    values: list[Any] = [fields[key] for key in fields if key in allowed]
    updates.append("updated_at_utc=?")
    values.append(_utc_now())
    values.append(job_id)

    with sqlite3.connect(path) as conn:
        conn.execute(
            f"UPDATE ingest_jobs SET {', '.join(updates)} WHERE job_id = ?",
            values,
        )


def get_job(path: Path, job_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM ingest_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    return _row_to_dict(row)


def _find_active_job(path: Path, school: str, major: str) -> dict[str, Any] | None:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT *
            FROM ingest_jobs
            WHERE target_school = ? AND target_major = ? AND status IN ('pending', 'running')
            LIMIT 1
            """,
            (school, major),
        ).fetchone()
    return _row_to_dict(row)


def upsert_freshness(
    path: Path,
    school: str,
    major: str,
    options_hash: str,
    run: IngestRun,
    max_cc: int | None,
    allow_non_numeric_keys: bool,
) -> None:
    del max_cc, allow_non_numeric_keys
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO ingest_freshness (
                target_school,
                target_major,
                options_hash,
                last_successful_run_id,
                ingested_at_utc,
                agreements_seen,
                rows_written
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                school,
                major,
                options_hash,
                run.run_id,
                _utc_now(),
                run.agreements_seen,
                run.rows_written,
            ),
        )


def get_freshness(
    path: Path, school: str, major: str, options_hash: str
) -> dict[str, Any] | None:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        hashes = conn.execute(
            """
            SELECT options_hash
            FROM ingest_freshness
            WHERE target_school = ? AND target_major = ?
            """,
            (school, major),
        ).fetchall()
        row = conn.execute(
            """
            SELECT *
            FROM ingest_freshness
            WHERE target_school = ? AND target_major = ? AND options_hash = ?
            """,
            (school, major, options_hash),
        ).fetchone()
        if row is None and len(hashes) == 1:
            fallback_hash = hashes[0][0]
            row = conn.execute(
                """
                SELECT *
                FROM ingest_freshness
                WHERE target_school = ? AND target_major = ? AND options_hash = ?
                """,
                (school, major, fallback_hash),
            ).fetchone()
    return _row_to_dict(row)


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


def query_schools(path: Path) -> list[str]:
    """Return distinct target_school values, sorted."""
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT target_school FROM articulation_rows ORDER BY target_school ASC"
        ).fetchall()
    return [r[0] for r in rows]


def query_majors(path: Path, target_school: str) -> list[str]:
    """Return distinct target_major values for a school, sorted."""
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT target_major FROM articulation_rows WHERE target_school = ? ORDER BY target_major ASC",
            (target_school,),
        ).fetchall()
    return [r[0] for r in rows]

