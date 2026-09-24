from __future__ import annotations

from pathlib import Path

import pytest
import requests

from src.assist.models import ArticulationRow, IngestRun
from src.assist.store import ensure_db, save_rows, save_run
from src.schedule.catalog import get_college_source
from src.schedule.models import CourseAvailability, ParsedSection
from src.schedule.providers import ScheduleProvider
from src.schedule.service import ScheduleService


class _FakeProvider(ScheduleProvider):
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []

    def supports_source(self, source) -> bool:
        return source.system in ("colleague_selfservice", "wvm_static")

    def search_course(
        self, *, source, term, course_code: str
    ) -> CourseAvailability:
        self.calls.append((term.label, source.cc_id, course_code))
        if course_code == "MATH 1B":
            return CourseAvailability(
                cc_id=source.cc_id,
                cc_name=source.cc_name,
                term=term.label,
                course_code=course_code,
                offered=True,
                sections=[
                    ParsedSection(
                        section_id="12345",
                        status="open",
                        modality="online",
                        title="Calculus II",
                        instructor="Ada Lovelace",
                    )
                ],
                source_url="https://example.edu/search",
                raw_summary="fixture",
            )
        return CourseAvailability(
            cc_id=source.cc_id,
            cc_name=source.cc_name,
            term=term.label,
            course_code=course_code,
            offered=False,
            sections=[],
            source_url="https://example.edu/search",
            raw_summary="fixture",
        )


def _seed_assist_rows(db_path: Path) -> None:
    ensure_db(db_path)
    run = IngestRun.create(
        target_school="University of California, Los Angeles",
        target_major="Computer Science",
        agreements_seen=1,
        rows_written=3,
    )
    save_run(db_path, run)
    save_rows(
        db_path,
        run.run_id,
        [
            ArticulationRow(
                target_school=run.target_school,
                target_major=run.target_major,
                target_requirement="MATH 31B",
                uc_equivalent="MATH 31B",
                cc_name="Evergreen Valley College",
                cc_id=2,
                course_code="MATH 1B",
                course_title="Calculus II",
                agreement_id="123",
                academic_year="2024-2025",
                source_url="/api/artifacts/123",
            ),
            ArticulationRow(
                target_school=run.target_school,
                target_major=run.target_major,
                target_requirement="MATH 31B",
                uc_equivalent="MATH 31B",
                cc_name="Evergreen Valley College",
                cc_id=2,
                course_code="MATH 1B",
                course_title="Calculus II",
                agreement_id="124",
                academic_year="2024-2025",
                source_url="/api/artifacts/124",
            ),
            ArticulationRow(
                target_school=run.target_school,
                target_major=run.target_major,
                target_requirement="MATH 31A",
                uc_equivalent="MATH 31A",
                cc_name="West Valley College",
                cc_id=80,
                course_code="MATH 1A",
                course_title="Calculus I",
                agreement_id="125",
                academic_year="2024-2025",
                source_url="/api/artifacts/125",
            ),
        ],
    )


def test_catalog_lookup() -> None:
    source = get_college_source(2)
    assert source.cc_name == "Evergreen Valley College"
    assert source.system == "colleague_selfservice"
    assert source.locations == ("EVC",)

    wvc = get_college_source(80)
    assert wvc.cc_name == "West Valley College"
    assert wvc.locations == ("WVC",)

    with pytest.raises(KeyError):
        get_college_source(9999)


def test_schedule_service_queries_distinct_assist_courses(tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    _seed_assist_rows(db_path)

    provider = _FakeProvider()
    service = ScheduleService(db_path=db_path, provider=provider)
    out = service.query(
        target_school="University of California, Los Angeles",
        target_major="Computer Science",
        term_label="Summer 2026",
        cc_id=None,
        requirement_filter="MATH 31",
    )

    assert len(out) == 2
    assert {item.course_code for item in out} == {"MATH 1A", "MATH 1B"}
    assert provider.calls == [
        ("Summer 2026", 2, "MATH 1B"),
        ("Summer 2026", 80, "MATH 1A"),
    ]


def test_schedule_service_raises_on_unsupported_source(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    _seed_assist_rows(db_path)

    class _UnsupportedProvider(_FakeProvider):
        def supports_source(self, source) -> bool:
            return False

    provider = _UnsupportedProvider()
    service = ScheduleService(db_path=db_path, provider=provider)

    with pytest.raises(ValueError, match="No provider configured for source system"):
        service.query(
            target_school="University of California, Los Angeles",
            target_major="Computer Science",
            term_label="Summer 2026",
            cc_id=2,
            requirement_filter="MATH 31B",
        )


def test_schedule_service_fail_soft_on_request_error(tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    _seed_assist_rows(db_path)

    class _FailingProvider(_FakeProvider):
        def search_course(self, *, source, term, course_code: str) -> CourseAvailability:
            raise requests.RequestException("timeout")

    provider = _FailingProvider()
    service = ScheduleService(db_path=db_path, provider=provider)
    out = service.query(
        target_school="University of California, Los Angeles",
        target_major="Computer Science",
        term_label="Summer 2026",
        cc_id=2,
        requirement_filter="MATH 31B",
    )

    assert len(out) == 1
    assert out[0].offered is False
    assert out[0].raw_summary == "[request_error type=RequestException]"


def test_schedule_service_contains_one_colleges_unexpected_exception(tmp_path: Path) -> None:
    """A bug in one college's adapter (e.g. an AttributeError from malformed portal JSON)
    must not blank out results for every other college in the same query."""
    db_path = tmp_path / "assist.sqlite3"
    _seed_assist_rows(db_path)

    class _OneCollegeBlowsUp(_FakeProvider):
        def search_course(self, *, source, term, course_code: str) -> CourseAvailability:
            if source.cc_id == 2:
                raise AttributeError("'NoneType' object has no attribute 'get'")
            return super().search_course(source=source, term=term, course_code=course_code)

    provider = _OneCollegeBlowsUp()
    service = ScheduleService(db_path=db_path, provider=provider)
    out = service.query(
        target_school="University of California, Los Angeles",
        target_major="Computer Science",
        term_label="Summer 2026",
        cc_id=None,
        requirement_filter="MATH 31",
    )

    assert len(out) == 2
    by_cc_id = {item.cc_id: item for item in out}
    assert by_cc_id[2].offered is False
    assert "AttributeError" in by_cc_id[2].raw_summary
    # cc_id=80 never raised, so it went through the normal (non-error) path.
    assert by_cc_id[80].raw_summary == "fixture"
    assert "AttributeError" not in by_cc_id[80].raw_summary


def test_query_skips_unsupported_colleges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import json
    from src.schedule import catalog

    db_path = tmp_path / "assist.sqlite3"
    _seed_assist_rows(db_path)
    entries = [
        {
            "cc_id": 2,
            "cc_name": "Evergreen Valley College",
            "system": "colleague_selfservice",
            "base_url": "https://example.edu",
            "locations": ["EVC"],
            "status": "unsupported",
            "note": "test",
        }
    ]
    catalog_file = tmp_path / "colleges.json"
    catalog_file.write_text(json.dumps(entries))
    catalog._reload(catalog_file)
    try:
        provider = _FakeProvider()
        service = ScheduleService(db_path=db_path, provider=provider)
        results = service.query(
            target_school="University of California, Los Angeles",
            target_major="Computer Science",
            term_label="Summer 2026",
        )
        assert results == []
        assert provider.calls == []
    finally:
        catalog._reload()
