from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.assist.models import ArticulationRow, IngestRun
from src.assist.store import (
    compute_options_hash,
    create_job,
    ensure_db,
    save_rows,
    save_run,
    update_job,
    upsert_freshness,
)


def _seed_rows(db_path: Path, school: str, major: str) -> IngestRun:
    run = IngestRun.create(
        target_school=school,
        target_major=major,
        agreements_seen=1,
        rows_written=1,
        max_cc=100,
        allow_non_numeric_keys=False,
    )
    save_run(db_path, run)
    row = ArticulationRow(
        target_school=school,
        target_major=major,
        target_requirement="Area A",
        uc_equivalent="COM SCI 1",
        cc_name="Test CC",
        cc_id=2,
        course_code="CS 1",
        course_title="Intro",
        agreement_id="123",
        academic_year="2024-2025",
        source_url="https://assist.org/123",
        notes="",
        raw_text="",
    )
    save_rows(db_path, run.run_id, [row])
    return run


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)

    from src.assist import config

    monkeypatch.setattr(config, "DB_PATH", db_path)

    import src.web.routers.ingest as ingest_router
    import src.web.routers.schools as schools_router
    import src.web.routers.search as search_router

    monkeypatch.setattr(ingest_router, "DB_PATH", db_path)
    monkeypatch.setattr(schools_router, "DB_PATH", db_path)

    class _EmptyService:
        def query(self, **_kwargs):  # type: ignore[no-untyped-def]
            return []

    search_router._service = _EmptyService()  # type: ignore[assignment]

    def _fake_run_ingest_job(
        job_id: str,
        school: str,
        major: str,
        max_cc: int | None,
        allow_non_numeric_keys: bool,
    ) -> None:
        update_job(
            db_path,
            job_id,
            status="running",
            started_at_utc=datetime.now(tz=timezone.utc).isoformat(),
        )
        run = _seed_rows(db_path, school, major)
        update_job(
            db_path,
            job_id,
            status="completed",
            completed_at_utc=datetime.now(tz=timezone.utc).isoformat(),
            run_id=run.run_id,
            rows_written=run.rows_written,
            agreements_seen=run.agreements_seen,
        )
        options_hash = compute_options_hash(max_cc, allow_non_numeric_keys)
        upsert_freshness(
            db_path,
            school,
            major,
            options_hash,
            run,
            max_cc,
            allow_non_numeric_keys,
        )

    monkeypatch.setattr(ingest_router, "run_ingest_job", _fake_run_ingest_job)

    from src.web.app import app

    with TestClient(app) as c:
        yield c


def _wait_until_complete(client: TestClient, job_id: str, timeout_s: float = 2.0) -> dict:
    start = time.time()
    while time.time() - start < timeout_s:
        res = client.get(f"/api/ingest/status/{job_id}")
        payload = res.json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for ingest completion")


def test_start_ingest_returns_job_id(client: TestClient) -> None:
    res = client.post(
        "/api/ingest",
        json={"target_school": "UCLA", "target_major": "Computer Science"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["job_id"]
    assert body["message"] == "Ingest job started."


def test_start_ingest_while_running(client: TestClient) -> None:
    import src.web.routers.ingest as ingest_router

    create_job(
        ingest_router.DB_PATH,
        "job-running",
        "UCLA",
        "Computer Science",
        8,
        False,
    )
    update_job(ingest_router.DB_PATH, "job-running", status="running")

    res = client.post(
        "/api/ingest",
        json={"target_school": "UCLA", "target_major": "Computer Science"},
    )
    assert res.status_code == 409


def test_get_status_pending(client: TestClient) -> None:
    import src.web.routers.ingest as ingest_router

    create_job(
        ingest_router.DB_PATH,
        "job-pending",
        "UCLA",
        "Computer Science",
        8,
        False,
    )
    res = client.get("/api/ingest/status/job-pending")
    assert res.status_code == 200
    assert res.json()["status"] == "pending"


def test_check_no_data(client: TestClient) -> None:
    res = client.get("/api/ingest/check?school=UCLA&major=Computer+Science")
    assert res.status_code == 200
    body = res.json()
    assert body["rows_exist"] is False
    assert body["freshness"] is None


def test_check_with_data(client: TestClient) -> None:
    start = client.post(
        "/api/ingest",
        json={"target_school": "UCLA", "target_major": "Computer Science"},
    )
    job_id = start.json()["job_id"]
    _wait_until_complete(client, job_id)

    res = client.get("/api/ingest/check?school=UCLA&major=Computer+Science")
    assert res.status_code == 200
    body = res.json()
    assert body["rows_exist"] is True
    assert body["freshness"] is not None
    assert "staleness_label" in body["freshness"]


def test_check_uses_actual_options(client: TestClient) -> None:
    import src.web.routers.ingest as ingest_router

    run = _seed_rows(ingest_router.DB_PATH, "UCLA", "Computer Science")
    upsert_freshness(
        ingest_router.DB_PATH,
        "UCLA",
        "Computer Science",
        compute_options_hash(8, False),
        run,
        8,
        False,
    )
    upsert_freshness(
        ingest_router.DB_PATH,
        "UCLA",
        "Computer Science",
        compute_options_hash(12, False),
        run,
        12,
        False,
    )

    res = client.get(
        "/api/ingest/check?school=UCLA&major=Computer+Science&max_cc=12&allow_non_numeric_keys=false"
    )
    assert res.status_code == 200
    assert res.json()["freshness"] is not None


def test_search_gated_without_data(client: TestClient) -> None:
    res = client.get("/api/search?school=UCLA&major=Computer+Science&term=Spring+2026")
    assert res.status_code == 409


def test_search_allowed_with_data(client: TestClient) -> None:
    start = client.post(
        "/api/ingest",
        json={"target_school": "UCLA", "target_major": "Computer Science"},
    )
    job_id = start.json()["job_id"]
    _wait_until_complete(client, job_id)

    res = client.get("/api/search?school=UCLA&major=Computer+Science&term=Spring+2026")
    assert res.status_code == 200
    assert "X-ASSIST-Staleness" in res.headers


def test_start_ingest_logs_unhandled_executor_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import src.web.routers.ingest as ingest_router

    def _boom(
        _job_id: str,
        _school: str,
        _major: str,
        _max_cc: int | None,
        _allow_non_numeric_keys: bool,
    ) -> None:
        raise RuntimeError("executor boom")

    monkeypatch.setattr(ingest_router, "run_ingest_job", _boom)

    with caplog.at_level("ERROR", logger="src.web.routers.ingest"):
        res = client.post(
            "/api/ingest",
            json={"target_school": "UCLA", "target_major": "Computer Science"},
        )
        assert res.status_code == 200

        start = time.time()
        while time.time() - start < 2.0:
            if any("Unhandled ingest executor failure" in rec.message for rec in caplog.records):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("Expected unhandled executor failure log")
