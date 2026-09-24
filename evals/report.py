"""Markdown reports for eval runs, committed under evals/results/."""
from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from src.llm.model import CallRecord

from .metrics import binary_metrics, calibration, choice_metrics, threshold_sweep


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _usage(records: Sequence[CallRecord]) -> list[str]:
    if not records:
        return ["Calls: not recorded by this backend"]
    tokens_in = sum(r.input_tokens or 0 for r in records)
    tokens_out = sum(r.output_tokens or 0 for r in records)
    latency = sum(r.latency_ms for r in records)
    lines = [f"Calls: {len(records)} ({sum(not r.ok for r in records)} failed)",
             f"Tokens: {tokens_in} in, {tokens_out} out",
             f"Latency: {latency} ms total, {latency // len(records)} ms mean"]
    price_in = os.environ.get("LLM_PRICE_INPUT_PER_MTOK")
    price_out = os.environ.get("LLM_PRICE_OUTPUT_PER_MTOK")
    if price_in and price_out:
        cost = tokens_in / 1e6 * float(price_in) + tokens_out / 1e6 * float(price_out)
        lines.append(f"Estimated cost: ${cost:.4f}")
    return lines


def _header(question: str, label: str, data_path: Path, today: date, cases: int, errors: Sequence) -> list[str]:
    return [f"# {question} eval: {label}", "", f"Date: {today.isoformat()}  ",
            f"Data: `{data_path}` ({cases} cases, {len(errors)} errors)", ""]


def _errors(errors: Sequence[tuple[str, str]]) -> list[str]:
    return ["", "## Errors", "", *(f"- {case_id}: {message}" for case_id, message in errors)] if errors else []


def render_equivalence(*, label: str, data_path: Path, run, records: Sequence[CallRecord], today: date) -> str:
    pairs = [(p, case.label) for case, p in run.predictions]
    lines = _header("course_equivalent", label, data_path, today, len(run.predictions) + len(run.errors), run.errors)
    if pairs:
        metrics = binary_metrics(pairs)
        lines += [f"Accuracy at 0.5: {_pct(metrics.accuracy_at_half)}  ",
                  f"Brier score: {metrics.brier:.4f} (lower is better)  ",
                  f"Positives: {metrics.positives} of {metrics.count}", "",
                  "## Threshold sweep", "", "| threshold | accepted | precision | recall |", "|---|---|---|---|"]
        lines += [f"| {r.threshold:.2f} | {r.accepted} | {_pct(r.precision)} | {_pct(r.recall)} |"
                  for r in threshold_sweep(pairs)]
        lines += ["", "## Calibration", "", "| bin | count | mean predicted | observed yes |", "|---|---|---|---|"]
        lines += [f"| {b.low:.1f}-{b.high:.1f} | {b.count} | {b.mean_predicted:.2f} | {_pct(b.observed_rate)} |"
                  for b in calibration(pairs)]
    lines += ["", "## Usage", "", *_usage(records), *_errors(run.errors)]
    return "\n".join(lines) + "\n"


def render_modality(*, label: str, data_path: Path, run, records: Sequence[CallRecord], today: date) -> str:
    pairs = [(case.label, predicted) for case, predicted in run.predictions]
    lines = _header("section_modality", label, data_path, today, len(run.predictions) + len(run.errors), run.errors)
    if pairs:
        metrics = choice_metrics(pairs)
        lines += [f"Accuracy: {_pct(metrics.accuracy)}", "", "## Confusion (expected -> predicted)", "",
                  *(f"- {expected} -> {predicted}: {n}" for (expected, predicted), n in sorted(metrics.confusion.items()))]
    lines += ["", "## Usage", "", *_usage(records), *_errors(run.errors)]
    return "\n".join(lines) + "\n"
