"""Data integrity: every catalog entry with system "replay" has a valid spec and vice versa."""
from __future__ import annotations

from src.schedule.catalog import list_college_sources
from src.schedule.replay.registry import SPECS_DIR, load_all_specs, load_specs_from


def test_all_committed_specs_load():
    specs = load_specs_from(SPECS_DIR)
    assert specs == load_all_specs()


def test_every_replay_catalog_entry_has_a_spec_and_every_spec_a_catalog_entry():
    catalog_ids = {s.cc_id for s in list_college_sources() if s.system == "replay"}
    spec_ids = set(load_all_specs())
    assert catalog_ids == spec_ids


def test_spec_names_match_catalog_names():
    by_id = {s.cc_id: s for s in list_college_sources()}
    for cc_id, spec in load_all_specs().items():
        assert spec.cc_name == by_id[cc_id].cc_name
