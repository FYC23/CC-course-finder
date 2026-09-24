from __future__ import annotations

from datetime import date
from pathlib import Path

from evals.datasets import EQUIVALENCE_FILE
from evals.report import render_equivalence
from evals.runner import EquivalenceRun


def _render(data_path: Path) -> str:
    run = EquivalenceRun(predictions=(), errors=())
    return render_equivalence(label="l", data_path=data_path, run=run, records=(), today=date(2026, 1, 1))


def test_data_path_under_the_repo_root_is_shown_relative_to_it():
    text = _render(EQUIVALENCE_FILE)
    assert "Data: `evals/data/course_equivalent.jsonl`" in text
    assert "Data: `/" not in text


def test_data_path_outside_the_repo_root_is_shown_as_given():
    outside = Path("/tmp/outside/course_equivalent.jsonl")
    text = _render(outside)
    assert "Data: `/tmp/outside/course_equivalent.jsonl`" in text
