from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from evals import runner as eval_runner
from evals.datasets import load_equivalence
from src.decisions.llm_provider import LlmDecisionProvider
from src.decisions.types import DecisionUnavailable
from src.llm.errors import LlmUnavailable
from src.llm.fake import FakeModel

cli = CliRunner()
_ROW = {"college": "c", "assist_code": "A 1", "assist_title": "t", "articulates_to": "u", "live_code": "B 1",
        "live_title": "t", "live_description": "", "source": "s"}


def _data(tmp_path: Path) -> Path:
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json.dumps({**_ROW, "id": i, "label": label}) for i, label in [("a", True), ("b", False)]) + "\n")
    return path


def _answer(p):
    return {"course_equivalent": {"reason": "r", "probability_yes": p}}


def test_run_equivalence_collects_predictions_and_errors(tmp_path):
    provider = LlmDecisionProvider(FakeModel(structured=[_answer(0.9), LlmUnavailable("down")]))
    run = eval_runner.run_equivalence(provider, load_equivalence(_data(tmp_path)))
    assert [(case.case_id, p) for case, p in run.predictions] == [("a", 0.9)]
    assert run.errors == (("b", "llm decision failed: down"),)


def test_provider_label_names_backend_and_model():
    provider = LlmDecisionProvider(FakeModel(model_id="m-1"))
    assert eval_runner.provider_label(provider) == "llm:fake:m-1"

    class _Jev:
        name = "jev"

    assert eval_runner.provider_label(_Jev()) == "jev"


def test_cli_writes_a_results_file(tmp_path, monkeypatch):
    provider = LlmDecisionProvider(FakeModel(structured=[_answer(0.95), _answer(0.1)], model_id="m-1"))
    monkeypatch.setattr(eval_runner, "decision_provider_from_env", lambda: provider)
    out_dir = tmp_path / "results"
    result = cli.invoke(eval_runner.app, ["course-equivalent", "--data", str(_data(tmp_path)), "--out-dir", str(out_dir)])
    assert result.exit_code == 0, result.output
    (written,) = out_dir.glob("*-course_equivalent-llm-fake-m-1.md")
    text = written.read_text()
    assert "Accuracy at 0.5: 100.0%" in text and "| 0.90 |" in text and "Calls: 2" in text


def test_cli_without_provider_exits_2(monkeypatch, tmp_path):
    monkeypatch.setattr(eval_runner, "decision_provider_from_env", lambda: None)
    result = cli.invoke(eval_runner.app, ["course-equivalent", "--data", str(_data(tmp_path))])
    assert result.exit_code == 2 and "DECISION_PROVIDER" in result.output


def test_cli_misconfigured_provider_exits_2(monkeypatch, tmp_path):
    def broken():
        raise DecisionUnavailable("jev client: no key")

    monkeypatch.setattr(eval_runner, "decision_provider_from_env", broken)
    result = cli.invoke(eval_runner.app, ["course-equivalent", "--data", str(_data(tmp_path))])
    assert result.exit_code == 2 and "no key" in result.output
