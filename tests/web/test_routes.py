from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.assist.models import ArticulationRow, IngestRun
from src.assist.store import ensure_db, save_rows, save_run


@pytest.fixture
def db(tmp_path: Path) -> Path:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)
    return db_path


def _seed(db_path: Path, schools: list[str], majors: list[str]) -> None:
    run = IngestRun.create(
        target_school=schools[0],
        target_major=majors[0],
        agreements_seen=1,
        rows_written=1,
    )
    save_run(db_path, run)
    rows = [
        ArticulationRow(
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
        for school in schools
        for major in majors
    ]
    save_rows(db_path, run.run_id, rows)


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)
    _seed(db_path, ["UCLA"], ["Computer Science"])
    return db_path


@pytest.fixture
def client(seeded_db: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Point DB_PATH at the test database
    from src.assist import config
    monkeypatch.setattr(config, "DB_PATH", seeded_db)

    # Replace _service singleton so schedule always returns []
    import src.web.routers.search as search_router
    search_router._service = None

    class _EmptyService:
        def query(self, **_kwargs):  # type: ignore[no-untyped-def]
            return []

    search_router._service = _EmptyService()  # type: ignore[assignment]

    from src.web.app import app
    with TestClient(app) as c:
        yield c


class TestSchools:
    def test_get_schools(self, client: TestClient) -> None:
        res = client.get("/api/schools")
        assert res.status_code == 200
        assert "UCLA" in res.json()


class TestMajors:
    def test_get_majors(self, client: TestClient) -> None:
        res = client.get("/api/majors?school=UCLA")
        assert res.status_code == 200
        assert "Computer Science" in res.json()


class TestSearch:
    def test_search_returns_shape(self, client: TestClient) -> None:
        res = client.get("/api/search?school=UCLA&major=Computer+Science&term=Spring+2026")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        if data:
            row = data[0]
            assert "cc_name" in row
            assert "course_code" in row
            assert "offered_this_term" in row
            assert "sections" in row

    def test_search_unknown_returns_empty_list(self, client: TestClient) -> None:
        res = client.get("/api/search?school=Unknown&major=Unknown&term=Spring+2026")
        assert res.status_code == 200
        assert res.json() == []

    def test_search_invalid_term(self, client: TestClient) -> None:
        res = client.get("/api/search?school=UCLA&major=Computer+Science&term=bad")
        assert res.status_code == 422

    def test_search_unsupported_provider_422(self, client: TestClient) -> None:
        import src.web.routers.search as search_router

        class _RaiseService:
            def query(self, **__):  # type: ignore[no-untyped-def]
                raise ValueError("No provider for system=banner")

        search_router._service = _RaiseService()  # type: ignore[assignment]

        res = client.get("/api/search?school=UCLA&major=Computer+Science&term=Spring+2026")
        assert res.status_code == 422

    def test_search_cc_not_in_catalog(self, client: TestClient) -> None:
        res = client.get("/api/search?school=UCLA&major=Computer+Science&term=Spring+2026")
        assert res.status_code == 200
        data = res.json()
        if data:
            assert data[0].get("offered_this_term") is None
