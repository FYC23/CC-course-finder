from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

import pytest
from typer.testing import CliRunner

from src.schedule.models import CourseAvailability, ParsedSection
from src.schedule.replay import cli as replay_cli
from src.schedule.replay.spec import load_spec

runner = CliRunner()

_SPEC = {
    "cc_id": 78, "cc_name": "Riverside City College", "version": 1, "recorded_at": "2026-09-23",
    "probe": {"course_code": "MATH-C2220", "term": "Fall 2026", "expect_min_rows": 1},
    "inputs": {"term": {"format": "{yy}{SEASON}", "seasons": {"fall": "FAL"}}},
    "steps": [{"id": "s", "method": "GET", "url": "https://example.edu/api", "query": {"t": "{term}"}}],
    "extract": {"kind": "json", "rows": "$.value[*]", "fields": {"section_id": "$.id"}},
}


class _StubProvider:
    def __init__(self, sections_by_code: dict[str, int]) -> None:
        self._by_code = sections_by_code

    def supports_source(self, source) -> bool:
        return source.system == "replay"

    def search_course(self, *, source, term, course_code: str) -> CourseAvailability:
        count = self._by_code.get(course_code, 0)
        sections = [ParsedSection(section_id=str(i), status="open", modality="unknown", title="", instructor="")
                    for i in range(count)]
        return CourseAvailability(cc_id=source.cc_id, cc_name=source.cc_name, term=term.label,
                                  course_code=course_code, offered=bool(sections), sections=sections,
                                  source_url="https://example.edu/api", raw_summary="stub")


@pytest.fixture
def specs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "78.json"
    path.write_text(json.dumps(_SPEC))
    loaded = MappingProxyType({78: load_spec(path)})
    monkeypatch.setattr(replay_cli, "load_all_specs", lambda: loaded)
    return loaded


def _fail_if_called():
    raise AssertionError("validate must load strictly, not through the cached runtime loader")


def test_validate_reports_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "78.json").write_text(json.dumps(_SPEC))
    monkeypatch.setattr(replay_cli, "SPECS_DIR", tmp_path)
    monkeypatch.setattr(replay_cli, "load_all_specs", _fail_if_called)
    result = runner.invoke(replay_cli.app, ["validate"])
    assert result.exit_code == 0, result.output
    assert "1 spec(s) valid" in result.stdout


def test_validate_reports_bad_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "78.json").write_text(json.dumps(_SPEC))
    (tmp_path / "1.json").write_text("{}")
    monkeypatch.setattr(replay_cli, "SPECS_DIR", tmp_path)
    monkeypatch.setattr(replay_cli, "load_all_specs", _fail_if_called)
    result = runner.invoke(replay_cli.app, ["validate"])
    assert result.exit_code == 1
    assert "1.json" in result.output


def test_run_prints_availability_json(specs, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(replay_cli, "_provider", lambda: _StubProvider({"MATH 1": 2}))
    result = runner.invoke(replay_cli.app, ["run", "--cc-id", "78", "--term", "Fall 2026", "--course", "MATH 1"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["offered"] is True and len(payload["sections"]) == 2


def test_run_unknown_cc_id_exits_2(specs):
    result = runner.invoke(replay_cli.app, ["run", "--cc-id", "1", "--term", "Fall 2026", "--course", "MATH 1"])
    assert result.exit_code == 2


def test_probe_pass_and_fail(specs, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(replay_cli, "_provider", lambda: _StubProvider({"MATH-C2220": 3}))
    ok = runner.invoke(replay_cli.app, ["probe"])
    assert ok.exit_code == 0 and "PASS 78 Riverside City College 3 row(s)" in ok.stdout

    monkeypatch.setattr(replay_cli, "_provider", lambda: _StubProvider({}))
    bad = runner.invoke(replay_cli.app, ["probe", "--cc-id", "78"])
    assert bad.exit_code == 1 and "FAIL 78 Riverside City College 0 row(s) (expected >= 1)" in bad.output


def test_probe_reports_exception_as_fail(specs, monkeypatch: pytest.MonkeyPatch):
    class _Boom(_StubProvider):
        def search_course(self, **kwargs):
            raise RuntimeError("kaboom")

    monkeypatch.setattr(replay_cli, "_provider", lambda: _Boom({}))
    result = runner.invoke(replay_cli.app, ["probe"])
    assert result.exit_code == 1 and "FAIL 78 Riverside City College RuntimeError: kaboom" in result.output
