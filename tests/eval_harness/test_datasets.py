from __future__ import annotations

from pathlib import Path

import pytest

from evals.datasets import (
    EQUIVALENCE_FILE, MODALITY_FILE, DatasetInvalid, load_equivalence, load_modality,
)


def test_committed_sets_load():
    equivalence = load_equivalence(EQUIVALENCE_FILE)
    assert len(equivalence) == 24 and sum(c.label for c in equivalence) == 9
    modality = load_modality(MODALITY_FILE)
    assert len(modality) == 7


def test_case_state_matches_question_builder():
    case = load_equivalence(EQUIVALENCE_FILE)[0]
    assert case.state()["assist_course"]["code"] == "MAT 1A"
    assert load_modality(MODALITY_FILE)[1].state()["has_timed_meetings"] is False


@pytest.mark.parametrize("line, message", [
    ('{"id": "x"}', "missing"),
    ('not json', "line 1"),
    ('{"id": "a", "college": "c", "assist_code": "A 1", "assist_title": "t", "articulates_to": "u", '
     '"live_code": "B 1", "live_title": "t", "live_description": "", "label": "yes", "source": "s"}', "label"),
])
def test_bad_equivalence_rows(tmp_path: Path, line, message):
    path = tmp_path / "cases.jsonl"
    path.write_text(line + "\n")
    with pytest.raises(DatasetInvalid, match=message):
        load_equivalence(path)


def test_duplicate_ids_and_bad_modality_label(tmp_path: Path):
    path = tmp_path / "m.jsonl"
    row = '{"id": "a", "raw_tokens": [], "locations": [], "has_timed_meetings": false, "label": "%s", "source": "s"}'
    path.write_text((row % "async_online") + "\n" + (row % "async_online") + "\n")
    with pytest.raises(DatasetInvalid, match="duplicate id 'a'"):
        load_modality(path)
    path.write_text((row % "zoom") + "\n")
    with pytest.raises(DatasetInvalid, match="label"):
        load_modality(path)
