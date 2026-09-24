"""Score a decision backend on the hand-labeled sets and write a markdown report.

    DECISION_PROVIDER=llm LLM_PROVIDER=<vendor> LLM_MODEL=<id> uv run python -m evals.runner course-equivalent
    DECISION_PROVIDER=jev uv run python -m evals.runner section-modality
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import typer

from src.decisions.factory import decision_provider_from_env
from src.decisions.questions import COURSE_EQUIVALENT, QUESTIONS, SECTION_MODALITY
from src.decisions.types import BooleanAnswer, ChoiceAnswer, DecisionProvider, DecisionUnavailable
from src.llm.errors import LlmError
from src.llm.model import CallRecord

from .datasets import (
    EQUIVALENCE_FILE, MODALITY_FILE, EquivalenceCase, ModalityCase, load_equivalence, load_modality,
)
from .report import render_equivalence, render_modality

app = typer.Typer(help="Decision evals: score the configured backend on hand-labeled cases.")
RESULTS_DIR = Path(__file__).parent / "results"


@dataclass(frozen=True)
class EquivalenceRun:
    predictions: tuple[tuple[EquivalenceCase, float], ...]
    errors: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ModalityRun:
    predictions: tuple[tuple[ModalityCase, str], ...]
    errors: tuple[tuple[str, str], ...]


def run_equivalence(provider: DecisionProvider, cases: Sequence[EquivalenceCase]) -> EquivalenceRun:
    question = {COURSE_EQUIVALENT: QUESTIONS[COURSE_EQUIVALENT]}
    predictions, errors = [], []
    for case in cases:
        try:
            answer = provider.decide(case.state(), question)[COURSE_EQUIVALENT]
        except DecisionUnavailable as err:
            errors.append((case.case_id, str(err)))
            continue
        if isinstance(answer, BooleanAnswer):
            predictions.append((case, answer.probability))
        else:
            errors.append((case.case_id, f"unexpected answer {type(answer).__name__}"))
    return EquivalenceRun(tuple(predictions), tuple(errors))


def run_modality(provider: DecisionProvider, cases: Sequence[ModalityCase]) -> ModalityRun:
    question = {SECTION_MODALITY: QUESTIONS[SECTION_MODALITY]}
    predictions, errors = [], []
    for case in cases:
        try:
            answer = provider.decide(case.state(), question)[SECTION_MODALITY]
        except DecisionUnavailable as err:
            errors.append((case.case_id, str(err)))
            continue
        if isinstance(answer, ChoiceAnswer):
            predictions.append((case, answer.choice))
        else:
            errors.append((case.case_id, f"unexpected answer {type(answer).__name__}"))
    return ModalityRun(tuple(predictions), tuple(errors))


def provider_label(provider: DecisionProvider) -> str:
    model = getattr(provider, "model", None)
    return f"{provider.name}:{model.provider}:{model.model_id}" if model is not None else provider.name


def _records(provider: DecisionProvider) -> tuple[CallRecord, ...]:
    model = getattr(provider, "model", None)
    return model.call_records() if model is not None else ()


def _provider() -> DecisionProvider:
    try:
        provider = decision_provider_from_env()
    except (LlmError, DecisionUnavailable, ValueError) as err:
        typer.echo(f"Decision backend misconfigured: {err}", err=True)
        raise typer.Exit(code=2) from err
    if provider is None:
        typer.echo("Set DECISION_PROVIDER=llm or jev to run an eval.", err=True)
        raise typer.Exit(code=2)
    return provider


def _write(out_dir: Path, question: str, label: str, text: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-")
    path = out_dir / f"{date.today().isoformat()}-{question}-{slug}.md"
    path.write_text(text)
    return path


@app.command("course-equivalent")
def course_equivalent(
    data: Path = typer.Option(EQUIVALENCE_FILE, help="JSON-lines cases."),
    limit: int = typer.Option(0, help="Score only the first N cases (0 = all)."),
    out_dir: Path = typer.Option(RESULTS_DIR, help="Where to write the report."),
) -> None:
    provider = _provider()
    cases = load_equivalence(data)
    run = run_equivalence(provider, cases[:limit] if limit else cases)
    label = provider_label(provider)
    text = render_equivalence(label=label, data_path=data, run=run, records=_records(provider), today=date.today())
    typer.echo(f"Wrote {_write(out_dir, COURSE_EQUIVALENT, label, text)}")


@app.command("section-modality")
def section_modality(
    data: Path = typer.Option(MODALITY_FILE, help="JSON-lines cases."),
    limit: int = typer.Option(0, help="Score only the first N cases (0 = all)."),
    out_dir: Path = typer.Option(RESULTS_DIR, help="Where to write the report."),
) -> None:
    provider = _provider()
    cases = load_modality(data)
    run = run_modality(provider, cases[:limit] if limit else cases)
    label = provider_label(provider)
    text = render_modality(label=label, data_path=data, run=run, records=_records(provider), today=date.today())
    typer.echo(f"Wrote {_write(out_dir, SECTION_MODALITY, label, text)}")


if __name__ == "__main__":
    app()
