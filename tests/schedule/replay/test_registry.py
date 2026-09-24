from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from src.schedule.errors import SpecInvalid
from src.schedule.replay.registry import load_specs_from

_SPEC = {
    "cc_id": 999, "cc_name": "Test College", "version": 1, "recorded_at": "2026-09-23",
    "probe": {"course_code": "MATH 1", "term": "Fall 2026"},
    "inputs": {"term": {"format": "{yyyy}{SEASON}", "seasons": {"fall": "70"}}},
    "steps": [{"id": "search", "method": "GET", "url": "https://example.edu/api", "query": {"t": "{term}"}}],
    "extract": {"kind": "json", "rows": "$.data[*]", "fields": {"section_id": "$.crn"}},
}


def _write(directory: Path, name: str, cc_id: int) -> None:
    (directory / name).write_text(json.dumps({**_SPEC, "cc_id": cc_id}))


def test_strict_raises_on_invalid_file(tmp_path: Path):
    _write(tmp_path, "1.json", 1)
    (tmp_path / "2.json").write_text("{}")
    with pytest.raises(SpecInvalid, match="2.json"):
        load_specs_from(tmp_path)


def test_strict_raises_on_name_mismatch(tmp_path: Path):
    _write(tmp_path, "5.json", 6)
    with pytest.raises(SpecInvalid, match="file name"):
        load_specs_from(tmp_path, strict=True)


def test_non_strict_skips_invalid_file_and_logs_it(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    _write(tmp_path, "1.json", 1)
    (tmp_path / "2.json").write_text("{}")
    _write(tmp_path, "3.json", 3)
    with caplog.at_level(logging.ERROR):
        specs = load_specs_from(tmp_path, strict=False)
    assert sorted(specs) == [1, 3]
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1 and "2.json" in errors[0].getMessage()


def test_non_strict_skips_name_mismatch(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    _write(tmp_path, "1.json", 1)
    _write(tmp_path, "5.json", 6)
    with caplog.at_level(logging.ERROR):
        specs = load_specs_from(tmp_path, strict=False)
    assert sorted(specs) == [1]
    assert any("5.json" in r.getMessage() and "file name" in r.getMessage() for r in caplog.records)


def test_non_strict_skips_a_second_file_with_the_same_cc_id(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    # A second file for cc_id 7 can only be named something other than 7.json, so the
    # file-name rule rejects it before the duplicate check; either way it is skipped.
    _write(tmp_path, "7.json", 7)
    _write(tmp_path, "07.json", 7)
    with caplog.at_level(logging.ERROR):
        specs = load_specs_from(tmp_path, strict=False)
    assert list(specs) == [7]
    assert any("07.json" in r.getMessage() for r in caplog.records)


def test_strict_raises_on_a_second_file_with_the_same_cc_id(tmp_path: Path):
    _write(tmp_path, "7.json", 7)
    _write(tmp_path, "07.json", 7)
    with pytest.raises(SpecInvalid, match="07.json"):
        load_specs_from(tmp_path)
