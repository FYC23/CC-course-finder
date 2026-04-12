from __future__ import annotations

import json
from pathlib import Path

import requests
from typer.testing import CliRunner

from src.assist.models import ArticulationRow, IngestRun
from src.assist.store import ensure_db, save_rows, save_run
from src.schedule import cli as schedule_cli

_RUNNER = CliRunner()
_BASE_ARGS = [
    "query",
    "--target-school",
    "University of California, Los Angeles",
    "--target-major",
    "Computer Science",
    "--term",
    "Summer 2026",
]


def test_cli_rejects_invalid_cc_id() -> None:
    result = _RUNNER.invoke(schedule_cli.app, [*_BASE_ARGS, "--cc-id", "9999"])
    assert result.exit_code == 2
    assert "No schedule source configured for cc_id=9999" in result.output


def test_cli_exits_code_2_on_bad_term(monkeypatch) -> None:
    class _FakeService:
        def __init__(self, db_path, provider) -> None:
            pass

        def query(self, **kwargs):
            raise ValueError("term must match Spring|Summer|Fall YYYY")

    monkeypatch.setattr(schedule_cli, "ScheduleService", _FakeService)
    result = _RUNNER.invoke(schedule_cli.app, _BASE_ARGS)
    assert result.exit_code == 2
    assert "Invalid input: term must match Spring|Summer|Fall YYYY" in result.output


def test_cli_exits_code_1_when_service_raises_request_exception(monkeypatch) -> None:
    class _FakeService:
        def __init__(self, db_path, provider) -> None:
            pass

        def query(self, **kwargs):
            raise requests.RequestException("network timeout")

    monkeypatch.setattr(schedule_cli, "ScheduleService", _FakeService)
    result = _RUNNER.invoke(schedule_cli.app, _BASE_ARGS)
    assert result.exit_code == 1
    assert "Schedule request failed: network timeout" in result.output


def _seed_row(db_path: Path) -> None:
    ensure_db(db_path)
    run = IngestRun.create(
        target_school="University of California, Los Angeles",
        target_major="Computer Science",
        agreements_seen=1,
        rows_written=1,
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
            )
        ],
    )


def test_cli_returns_fail_soft_row_on_provider_request_error(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    _seed_row(db_path)
    monkeypatch.setattr(schedule_cli, "DB_PATH", db_path)

    class _FailingProvider:
        def supports_source(self, source) -> bool:
            return True

        def search_course(self, *, source, term, course_code):
            raise requests.RequestException("network timeout")

    monkeypatch.setattr(schedule_cli, "BannerEllucianProvider", _FailingProvider)
    result = _RUNNER.invoke(schedule_cli.app, [*_BASE_ARGS, "--cc-id", "2"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["offered"] is False
    assert payload[0]["raw_summary"] == "[request_error type=RequestException]"


def test_cli_rejects_unsupported_source_system(monkeypatch) -> None:
    class _FakeProvider:
        def supports_source(self, source) -> bool:
            return False

    monkeypatch.setattr(schedule_cli, "BannerEllucianProvider", _FakeProvider)
    result = _RUNNER.invoke(schedule_cli.app, [*_BASE_ARGS, "--cc-id", "2"])
    assert result.exit_code == 2
    assert "No provider configured for source system='banner'" in result.output


def test_cli_all_ccs_passes_none_cc_id(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "assist.sqlite3"
    _seed_row(db_path)
    monkeypatch.setattr(schedule_cli, "DB_PATH", db_path)

    received_cc_ids: list[int | None] = []

    class _SpyService:
        def __init__(self, db_path, provider) -> None:
            pass

        def query(self, *, cc_id, **kwargs):
            received_cc_ids.append(cc_id)
            return []

    monkeypatch.setattr(schedule_cli, "ScheduleService", _SpyService)
    result = _RUNNER.invoke(schedule_cli.app, _BASE_ARGS)  # default cc_id=0

    assert result.exit_code == 0
    assert received_cc_ids == [None]
