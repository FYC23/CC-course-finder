from __future__ import annotations

from pathlib import Path

import pytest

from src.matching.seeds import SeedInvalid, load_seed_aliases, load_subject_renames
from src.schedule.catalog import list_college_sources


def test_committed_seeds_load_strictly():
    aliases = load_seed_aliases()
    renames = load_subject_renames()
    assert len(aliases) == 27 * 3
    assert {(r.cc_id, r.old_subject, r.new_subject) for r in renames} >= {
        (78, "MAT", "MATH"), (148, "ENG", "ENGL"), (149, "COM", "COMM"),
    }
    pairs = {(a.cc_id, a.old_code, a.new_code) for a in aliases}
    assert (78, "MAT-1B", "MATH-C2220") in pairs and (149, "ENGL-1B", "ENGL-C1003") in pairs
    assert all(a.status == "verified" and a.confidence == 1.0 and not a.reviewed for a in aliases)


def test_every_seeded_college_is_in_the_catalog():
    known = {s.cc_id for s in list_college_sources()}
    seeded = {a.cc_id for a in load_seed_aliases()} | {r.cc_id for r in load_subject_renames()}
    assert seeded <= known


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "seed.csv"
    path.write_text(text)
    return path


@pytest.mark.parametrize("body, message", [
    ("cc_id,old_code,new_code,source,evidence\n", "header must be"),
    ("cc_ids,old_code,new_code,source,evidence\nx,A 1,B 1,s,e\n", r"seed.csv:2: cc_ids"),
    ("cc_ids,old_code,new_code,source,evidence\n1,A,B 1,s,e\n", r"seed.csv:2: old_code 'A'"),
    ("cc_ids,old_code,new_code,source,evidence\n1,A 1,B 1,,e\n", r"seed.csv:2: source"),
])
def test_bad_alias_seed_names_file_and_line(tmp_path, body, message):
    with pytest.raises(SeedInvalid, match=message):
        load_seed_aliases(_write(tmp_path, body))


def test_bad_rename_subject_is_rejected(tmp_path):
    path = _write(tmp_path, "cc_ids,old_subject,new_subject,source,evidence\n1,M4T,MATH,s,e\n")
    with pytest.raises(SeedInvalid, match="old_subject 'M4T'"):
        load_subject_renames(path)
