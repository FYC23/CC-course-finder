from __future__ import annotations

import requests
from typer.testing import CliRunner

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


def test_cli_exits_code_1_on_request_failure(monkeypatch) -> None:
    class _FakeService:
        def __init__(self, db_path, provider) -> None:
            pass

        def query(self, **kwargs):
            raise requests.RequestException("network timeout")

    monkeypatch.setattr(schedule_cli, "ScheduleService", _FakeService)
    result = _RUNNER.invoke(schedule_cli.app, _BASE_ARGS)
    assert result.exit_code == 1
    assert "Schedule request failed: network timeout" in result.output
