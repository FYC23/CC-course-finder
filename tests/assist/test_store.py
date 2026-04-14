from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.assist.models import ArticulationRow, IngestRun
from src.assist.store import (
    _find_active_job,
    compute_options_hash,
    create_job,
    ensure_db,
    get_freshness,
    get_job,
    has_rows_for,
    query_majors,
    query_rows,
    query_schools,
    save_rows,
    save_run,
    update_job,
    upsert_freshness,
)


def test_store_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)
    run = IngestRun.create(
        target_school="University of California, Los Angeles",
        target_major="Computer Science",
        agreements_seen=1,
        rows_written=1,
    )
    save_run(db_path, run)

    row = ArticulationRow(
        target_school=run.target_school,
        target_major=run.target_major,
        target_requirement="MATH 31B",
        uc_equivalent="MATH 31B",
        cc_name="De Anza College",
        cc_id=54,
        course_code="MATH 1B",
        course_title="Calculus II",
        agreement_id="12345678",
        academic_year="2024-2025",
        source_url="/api/artifacts/12345678",
        notes="fixture",
        raw_text="raw",
    )
    inserted = save_rows(db_path, run.run_id, [row])
    assert inserted == 1

    found = query_rows(
        db_path,
        target_school=run.target_school,
        target_major=run.target_major,
        requirement_filter="31B",
    )
    assert len(found) == 1
    assert found[0].course_code == "MATH 1B"


def test_query_schools_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)
    assert [] == query_schools(db_path)


def test_query_schools_populated(tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)
    run = IngestRun.create(
        target_school="UC Berkeley",
        target_major="EECS",
        agreements_seen=1,
        rows_written=1,
    )
    save_run(db_path, run)
    row = ArticulationRow(
        target_school="UC Berkeley",
        target_major="EECS",
        target_requirement="MATH 1A",
        uc_equivalent="MATH 1A",
        cc_name="De Anza",
        cc_id=54,
        course_code="MATH 1A",
        course_title="Calc I",
        agreement_id="1",
        academic_year="2024-2025",
        source_url="https://a.b",
        notes="",
        raw_text="",
    )
    save_rows(db_path, run.run_id, [row])

    schools = query_schools(db_path)
    assert schools == ["UC Berkeley"]


def test_query_majors_filters_by_school(tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)
    run = IngestRun.create(
        target_school="UCLA",
        target_major="Computer Science",
        agreements_seen=1,
        rows_written=1,
    )
    save_run(db_path, run)
    row = ArticulationRow(
        target_school="UCLA",
        target_major="Computer Science",
        target_requirement="MATH 1A",
        uc_equivalent="MATH 1A",
        cc_name="De Anza",
        cc_id=54,
        course_code="MATH 1A",
        course_title="Calc I",
        agreement_id="1",
        academic_year="2024-2025",
        source_url="https://a.b",
        notes="",
        raw_text="",
    )
    save_rows(db_path, run.run_id, [row])

    assert query_majors(db_path, "UCLA") == ["Computer Science"]
    assert query_majors(db_path, "UC Berkeley") == []


def test_has_rows_for_empty_db(tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)
    assert has_rows_for(db_path, "UCLA", "Computer Science") is False


def test_has_rows_for_after_save_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)
    run = IngestRun.create(
        target_school="UCLA",
        target_major="Computer Science",
        agreements_seen=1,
        rows_written=0,
    )
    save_run(db_path, run)
    row = ArticulationRow(
        target_school="UCLA",
        target_major="Computer Science",
        target_requirement="MATH 31B",
        uc_equivalent="MATH 31B",
        cc_name="De Anza",
        cc_id=54,
        course_code="MATH 1B",
        course_title="Calculus II",
        agreement_id="1",
        academic_year="2024-2025",
        source_url="https://assist.org/1",
        notes="",
        raw_text="",
    )
    save_rows(db_path, run.run_id, [row])
    assert has_rows_for(db_path, "UCLA", "Computer Science") is True


def test_create_job_and_get_job(tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)
    create_job(db_path, "job-1", "UCLA", "Computer Science", 8, False)

    job = get_job(db_path, "job-1")
    assert job is not None
    assert job["status"] == "pending"
    assert job["target_school"] == "UCLA"
    assert job["target_major"] == "Computer Science"
    assert job["max_cc"] == 8
    assert job["allow_non_numeric_keys"] == 0


def test_update_job_partial(tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)
    create_job(db_path, "job-2", "UCLA", "Computer Science", 8, False)
    update_job(db_path, "job-2", status="running")

    job = get_job(db_path, "job-2")
    assert job is not None
    assert job["status"] == "running"
    assert job["started_at_utc"] is None


def test_update_job_sets_updated_at_utc(tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)
    create_job(db_path, "job-3", "UCLA", "Computer Science", 8, False)
    before = get_job(db_path, "job-3")
    assert before is not None
    before_updated_at = before["updated_at_utc"]

    update_job(db_path, "job-3", status="running")
    after = get_job(db_path, "job-3")
    assert after is not None
    assert after["updated_at_utc"] != before_updated_at


def test_find_active_job_none(tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)
    assert _find_active_job(db_path, "UCLA", "Computer Science") is None


def test_find_active_job_one_running(tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)
    create_job(db_path, "job-4", "UCLA", "Computer Science", 8, False)
    update_job(db_path, "job-4", status="running")

    job = _find_active_job(db_path, "UCLA", "Computer Science")
    assert job is not None
    assert job["job_id"] == "job-4"
    assert job["status"] == "running"


def test_upsert_freshness_replace(tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)
    run1 = IngestRun.create(
        target_school="UCLA",
        target_major="Computer Science",
        agreements_seen=1,
        rows_written=10,
        max_cc=8,
        allow_non_numeric_keys=False,
    )
    run2 = IngestRun.create(
        target_school="UCLA",
        target_major="Computer Science",
        agreements_seen=2,
        rows_written=20,
        max_cc=8,
        allow_non_numeric_keys=False,
    )
    options_hash = compute_options_hash(8, False)
    upsert_freshness(db_path, "UCLA", "Computer Science", options_hash, run1, 8, False)
    upsert_freshness(db_path, "UCLA", "Computer Science", options_hash, run2, 8, False)

    freshness = get_freshness(db_path, "UCLA", "Computer Science", options_hash)
    assert freshness is not None
    assert freshness["last_successful_run_id"] == run2.run_id
    assert freshness["rows_written"] == 20

    with sqlite3.connect(db_path) as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM ingest_freshness WHERE target_school = ? AND target_major = ?",
            ("UCLA", "Computer Science"),
        ).fetchone()
    assert total is not None
    assert total[0] == 1


def test_compute_options_hash() -> None:
    assert compute_options_hash(8, False) == compute_options_hash(8, False)
    assert compute_options_hash(8, False) != compute_options_hash(12, False)
    assert compute_options_hash(8, False) != compute_options_hash(8, True)


def test_ingest_runs_columns_backward_compat(tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE ingest_runs (
                run_id TEXT PRIMARY KEY,
                created_at_utc TEXT NOT NULL,
                target_school TEXT NOT NULL,
                target_major TEXT NOT NULL,
                agreements_seen INTEGER NOT NULL,
                rows_written INTEGER NOT NULL
            )
            """
        )
    ensure_db(db_path)
    run = IngestRun(
        run_id="run-old",
        created_at_utc=datetime.now(tz=timezone.utc).isoformat(),
        target_school="UCLA",
        target_major="Computer Science",
        agreements_seen=1,
        rows_written=1,
        max_cc=8,
        allow_non_numeric_keys=False,
    )
    save_run(db_path, run)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT max_cc, allow_non_numeric_keys
            FROM ingest_runs
            WHERE run_id = ?
            """,
            ("run-old",),
        ).fetchone()
    assert row == (8, 0)


def test_ensure_db_enables_wal_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)
    with sqlite3.connect(db_path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()
    assert mode is not None
    assert str(mode[0]).lower() == "wal"


def test_create_job_retries_when_database_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)

    import src.assist.store as store

    real_connect = store.sqlite3.connect
    attempts = {"count": 0}

    def _flaky_connect(*args, **kwargs):  # type: ignore[no-untyped-def]
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(store.sqlite3, "connect", _flaky_connect)

    create_job(db_path, "job-retry", "UCLA", "Computer Science", 8, False)
    job = get_job(db_path, "job-retry")
    assert attempts["count"] >= 2
    assert job is not None

