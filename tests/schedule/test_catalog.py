"""Tests for src/schedule/catalog.py"""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from src.schedule.catalog import (
    _validate_entry,
    _load,
    _reload,
    get_college_source,
    find_college_source_by_name,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def restore_catalog():
    """Reload the real colleges.json after every test that calls _reload."""
    yield
    _reload()


def _write_json(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "colleges.json"
    p.write_text(json.dumps(data))
    return p


_VALID_ENTRY = {
    "cc_id": 999,
    "cc_name": "Test College",
    "system": "banner",
    "base_url": "https://example.edu/Student/Courses/SearchResult",
    "locations": ["TC"],
}


# ---------------------------------------------------------------------------
# _validate_entry — error paths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing_key", ["cc_id", "cc_name", "system", "base_url", "locations"])
def test_validate_entry_missing_key(missing_key: str):
    entry = {k: v for k, v in _VALID_ENTRY.items() if k != missing_key}
    with pytest.raises(ValueError, match=missing_key):
        _validate_entry(entry)


def test_validate_entry_unknown_system():
    entry = {**_VALID_ENTRY, "system": "peoplesoft"}
    with pytest.raises(ValueError, match="Unknown system"):
        _validate_entry(entry)


def test_validate_entry_empty_locations():
    entry = {**_VALID_ENTRY, "locations": []}
    with pytest.raises(ValueError, match="Empty locations"):
        _validate_entry(entry)


def test_validate_entry_source_url_non_string():
    entry = {**_VALID_ENTRY, "source_url": 42}
    with pytest.raises(ValueError, match="source_url must be string"):
        _validate_entry(entry)


def test_validate_entry_valid_with_source_url():
    entry = {**_VALID_ENTRY, "source_url": "https://example.edu/schedule"}
    _validate_entry(entry)  # must not raise


# ---------------------------------------------------------------------------
# _load — error paths
# ---------------------------------------------------------------------------

def test_load_missing_file():
    with pytest.raises(RuntimeError, match="missing"):
        _load(Path("/nonexistent/colleges.json"))


def test_load_malformed_json(tmp_path: Path):
    bad = tmp_path / "colleges.json"
    bad.write_text("not json {{{")
    with pytest.raises(RuntimeError, match="corrupt"):
        _load(bad)


def test_load_missing_required_key(tmp_path: Path):
    data = [{k: v for k, v in _VALID_ENTRY.items() if k != "system"}]
    p = _write_json(tmp_path, data)
    with pytest.raises(ValueError, match="system"):
        _load(p)


def test_load_unknown_system(tmp_path: Path):
    data = [{**_VALID_ENTRY, "system": "colleague"}]
    p = _write_json(tmp_path, data)
    with pytest.raises(ValueError, match="Unknown system"):
        _load(p)


def test_load_empty_locations(tmp_path: Path):
    data = [{**_VALID_ENTRY, "locations": []}]
    p = _write_json(tmp_path, data)
    with pytest.raises(ValueError, match="Empty locations"):
        _load(p)


# ---------------------------------------------------------------------------
# _reload
# ---------------------------------------------------------------------------

def test_reload_loads_new_entries(tmp_path: Path):
    data = [_VALID_ENTRY]
    p = _write_json(tmp_path, data)
    _reload(p)
    src = get_college_source(999)
    assert src.cc_name == "Test College"
    assert src.locations == ("TC",)


def test_reload_replaces_old_entries(tmp_path: Path):
    p = _write_json(tmp_path, [_VALID_ENTRY])
    _reload(p)
    with pytest.raises(KeyError):
        get_college_source(2)  # EVC gone after reload


def test_reload_restores_original():
    # autouse fixture calls _reload() after test — verify EVC is back
    _reload(Path("/nonexistent") if False else None)  # no-op path
    src = get_college_source(2)
    assert src.cc_name == "Evergreen Valley College"


def test_reload_raises_on_bad_input(tmp_path: Path):
    bad = tmp_path / "colleges.json"
    bad.write_text("[]invalid")
    with pytest.raises(RuntimeError):
        _reload(bad)


# ---------------------------------------------------------------------------
# Smoke tests over real colleges.json (parametrized)
# ---------------------------------------------------------------------------

def _all_entries() -> list[dict]:
    data_file = Path(__file__).parent.parent.parent / "src" / "schedule" / "data" / "colleges.json"
    return json.loads(data_file.read_text())


@pytest.mark.parametrize("entry", _all_entries(), ids=lambda e: e.get("cc_name", "?"))
def test_validate_all_entries(entry: dict):
    _validate_entry(entry)


@pytest.mark.parametrize("entry", _all_entries(), ids=lambda e: e.get("cc_name", "?"))
def test_get_college_source_all_entries(entry: dict):
    src = get_college_source(entry["cc_id"])
    assert src.cc_id == entry["cc_id"]
    assert src.system in ("banner", "wvm_static", "banner_ssb_classic", "vsb_4cd")
    assert len(src.locations) > 0


@pytest.mark.parametrize("entry", _all_entries(), ids=lambda e: e.get("cc_name", "?"))
def test_find_by_name_all_entries(entry: dict):
    # Use full cc_name — should always resolve to exactly one match
    src = find_college_source_by_name(entry["cc_name"])
    assert src.cc_id == entry["cc_id"]


# ---------------------------------------------------------------------------
# find_college_source_by_name edge cases
# ---------------------------------------------------------------------------

def test_find_by_name_no_match():
    with pytest.raises(KeyError, match="No schedule source"):
        find_college_source_by_name("Nonexistent University of Nowhere")


def test_find_by_name_ambiguous(tmp_path: Path):
    data = [
        {**_VALID_ENTRY, "cc_id": 1, "cc_name": "Valley College North"},
        {**_VALID_ENTRY, "cc_id": 2, "cc_name": "Valley College South"},
    ]
    p = _write_json(tmp_path, data)
    _reload(p)
    with pytest.raises(KeyError, match="Ambiguous"):
        find_college_source_by_name("valley college")
