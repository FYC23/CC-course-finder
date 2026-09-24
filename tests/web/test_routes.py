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
    search_router._service_db_path = None

    class _EmptyService:
        def query(self, **_kwargs):  # type: ignore[no-untyped-def]
            return []

    search_router._service = _EmptyService()  # type: ignore[assignment]
    search_router._service_db_path = seeded_db

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

    def test_search_unknown_returns_409(self, client: TestClient) -> None:
        res = client.get("/api/search?school=Unknown&major=Unknown&term=Spring+2026")
        assert res.status_code == 409

    def test_search_invalid_term(self, client: TestClient) -> None:
        res = client.get("/api/search?school=UCLA&major=Computer+Science&term=bad")
        assert res.status_code == 422

    def test_search_unsupported_provider_422(self, client: TestClient) -> None:
        import src.web.routers.search as search_router

        class _RaiseService:
            def query(self, **__):  # type: ignore[no-untyped-def]
                raise ValueError("No provider for system=banner")

        search_router._service = _RaiseService()  # type: ignore[assignment]
        from src.assist import config

        search_router._service_db_path = config.DB_PATH

        res = client.get("/api/search?school=UCLA&major=Computer+Science&term=Spring+2026")
        assert res.status_code == 422

    def test_search_cc_not_in_catalog(self, client: TestClient) -> None:
        res = client.get("/api/search?school=UCLA&major=Computer+Science&term=Spring+2026")
        assert res.status_code == 200
        data = res.json()
        if data:
            assert data[0].get("offered_this_term") is None


def test_search_uses_current_config_db_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "assist.sqlite3"
    ensure_db(db_path)
    _seed(db_path, ["TEST-UC-SEARCH"], ["Major A"])

    from src.assist import config
    import src.web.routers.search as search_router
    from src.web.app import app

    monkeypatch.setattr(config, "DB_PATH", db_path)
    search_router._service = None
    search_router._service_db_path = None

    class _EmptyService:
        def query(self, **_kwargs):  # type: ignore[no-untyped-def]
            return []

    search_router._service = _EmptyService()  # type: ignore[assignment]
    search_router._service_db_path = db_path

    with TestClient(app) as client:
        res = client.get("/api/search?school=TEST-UC-SEARCH&major=Major+A&term=Spring+2026")
    assert res.status_code == 200


def test_get_service_rebuilds_when_db_path_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.web.routers.search as search_router
    from src.assist import config

    path_a = tmp_path / "a.sqlite3"
    path_b = tmp_path / "b.sqlite3"
    created: list[Path] = []

    class _FakeService:
        def __init__(self, *, db_path: Path, provider_factory: object) -> None:
            created.append(db_path)
            self.db_path = db_path
            self.provider_factory = provider_factory

        def query(self, **_kwargs):  # type: ignore[no-untyped-def]
            return []

    monkeypatch.setattr(search_router, "ScheduleService", _FakeService)  # type: ignore[assignment]
    factory = lambda: object()  # noqa: E731
    monkeypatch.setattr(search_router, "build_composite_provider", factory)

    search_router._service = None
    search_router._service_db_path = None
    monkeypatch.setattr(config, "DB_PATH", path_a)
    first = search_router._get_service()

    monkeypatch.setattr(config, "DB_PATH", path_b)
    second = search_router._get_service()

    assert first is not second
    assert created == [path_a, path_b]
    # Each college gets a fresh provider from the factory, so lookups can run in parallel.
    assert first.provider_factory is factory


def test_search_accepts_timezone_and_returns_fit(client, monkeypatch):
    from datetime import date, time

    from src.schedule.models import CourseAvailability, Meeting, ParsedSection
    from src.web.routers import search as search_router

    class _Svc:
        def query(self, **kwargs):
            return [CourseAvailability(
                cc_id=2, cc_name="Test CC", term="Fall 2026", course_code="CS 1", offered=True,
                sections=[ParsedSection(
                    section_id="9", status="open", modality="in_person", title="T", instructor="",
                    meetings=(Meeting(days=("M",), start_local=time(6, 30), end_local=time(8, 0),
                                      start_date=date(2026, 8, 24)),))],
                source_url="https://example.edu")]

    monkeypatch.setattr(search_router, "_get_service", lambda: _Svc())
    res = client.get("/api/search", params={"school": "UCLA", "major": "Computer Science",
                                            "term": "Fall 2026", "tz": "Asia/Shanghai"})
    assert res.status_code == 200
    section = res.json()[0]["sections"][0]
    assert section["fit"] == "fits"
    assert section["meetings"][0]["start_local"] == "06:30"


def test_search_without_timezone_has_null_fit(client, monkeypatch):
    from src.schedule.models import CourseAvailability, ParsedSection
    from src.web.routers import search as search_router

    class _Svc:
        def query(self, **kwargs):
            return [CourseAvailability(cc_id=2, cc_name="Test CC", term="Fall 2026", course_code="CS 1",
                                       offered=True, sections=[ParsedSection("9", "open", "unknown", "T", "")],
                                       source_url="https://example.edu")]

    monkeypatch.setattr(search_router, "_get_service", lambda: _Svc())
    res = client.get("/api/search", params={"school": "UCLA", "major": "Computer Science", "term": "Fall 2026"})
    assert res.status_code == 200
    assert res.json()[0]["sections"][0]["fit"] is None


@pytest.mark.parametrize("tz", ["Mars/Olympus_Mons", "../../etc/passwd", "UTC+8"])
def test_search_rejects_unknown_timezone(client, tz):
    res = client.get("/api/search", params={"school": "UCLA", "major": "Computer Science",
                                            "term": "Fall 2026", "tz": tz})
    assert res.status_code == 422


def _stream_events(res) -> list[dict]:
    import json

    return [json.loads(line) for line in res.text.splitlines() if line.strip()]


class _StreamService:
    """Plans one live college (cc_id 2, course CS 1) and yields it from iter_results."""

    def __init__(self, *, colleges=(2,), fail: Exception | None = None) -> None:
        self._colleges = colleges
        self._fail = fail

    def plan(self, **kwargs):
        from src.schedule.catalog import get_college_source
        from src.schedule.service import CollegeLookups, QueryPlan
        from src.schedule.term import parse_term_label

        return QueryPlan(term=parse_term_label(kwargs["term_label"]), colleges=tuple(
            CollegeLookups(source=get_college_source(cc), course_codes=("CS 1",))
            for cc in self._colleges))

    def iter_results(self, plan):
        from src.schedule.models import CourseAvailability, ParsedSection
        from src.schedule.service import CollegeResult

        if self._fail is not None:
            raise self._fail
        for college in plan.colleges:
            yield CollegeResult(cc_id=college.source.cc_id, availabilities=(CourseAvailability(
                cc_id=college.source.cc_id, cc_name="Test CC", term=plan.term.label,
                course_code="CS 1", offered=True,
                sections=[ParsedSection("9", "open", "async_online", "T", "")],
                source_url="https://example.edu"),))


_STREAM_PARAMS = {"school": "UCLA", "major": "Computer Science", "term": "Fall 2026"}


def test_search_stream_sends_start_then_each_college_then_done(client, monkeypatch):
    from src.web.routers import search as search_router

    monkeypatch.setattr(search_router, "_get_service", lambda: _StreamService())
    res = client.get("/api/search/stream", params={**_STREAM_PARAMS, "tz": "Asia/Shanghai"})

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/x-ndjson")
    start, college, done = _stream_events(res)
    assert start == {"type": "start", "total": 1, "results": []}
    assert (college["type"], college["cc_id"], college["done"], college["total"]) == ("college", 2, 1, 1)
    [row] = college["results"]
    assert (row["course_code"], row["offered_this_term"]) == ("CS 1", True)
    assert row["sections"][0]["fit"] == "async"
    assert done == {"type": "done", "done": 1, "total": 1}


def test_search_stream_sends_articulation_only_rows_up_front(client, monkeypatch):
    """Colleges with no live schedule lookup are known at once; show them immediately."""
    from src.web.routers import search as search_router

    monkeypatch.setattr(search_router, "_get_service", lambda: _StreamService(colleges=()))
    start, done = _stream_events(client.get("/api/search/stream", params=_STREAM_PARAMS))

    assert start["total"] == 0
    [row] = start["results"]
    assert (row["cc_id"], row["course_code"], row["offered_this_term"]) == (2, "CS 1", None)
    assert done == {"type": "done", "done": 0, "total": 0}


def test_search_stream_reports_failure_mid_stream(client, monkeypatch, caplog):
    from src.web.routers import search as search_router

    monkeypatch.setattr(search_router, "_get_service",
                        lambda: _StreamService(fail=RuntimeError("secret internals")))
    events = _stream_events(client.get("/api/search/stream", params=_STREAM_PARAMS))

    assert events[0]["type"] == "start"
    assert events[-1] == {"type": "error", "detail": "Schedule lookup failed partway through."}
    assert "secret internals" in caplog.text


@pytest.mark.parametrize("params,status", [
    ({**_STREAM_PARAMS, "term": "bad"}, 422),
    ({**_STREAM_PARAMS, "tz": "Mars/Olympus_Mons"}, 422),
    ({**_STREAM_PARAMS, "school": "Unknown"}, 409),
])
def test_search_stream_rejects_bad_requests_before_streaming(client, params, status):
    assert client.get("/api/search/stream", params=params).status_code == status


def test_search_stream_unsupported_provider_is_422(client, monkeypatch):
    from src.web.routers import search as search_router

    class _Unsupported:
        def plan(self, **_):
            raise ValueError("No provider configured for source system='x'")

    monkeypatch.setattr(search_router, "_get_service", lambda: _Unsupported())
    assert client.get("/api/search/stream", params=_STREAM_PARAMS).status_code == 422
