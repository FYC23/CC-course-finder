from __future__ import annotations

from pathlib import Path

from src.assist.models import ArticulationRow, IngestRun
from src.assist.store import ensure_db, query_rows, save_rows, save_run


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

