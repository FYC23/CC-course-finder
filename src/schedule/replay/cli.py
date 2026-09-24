"""Manual tools for replay specs: validate them, run one live lookup, or probe each college.

    uv run python -m src.schedule.replay.cli validate
    uv run python -m src.schedule.replay.cli run --cc-id 27 --term "Fall 2026" --course "MATH 400"
    uv run python -m src.schedule.replay.cli probe [--cc-id 27]

``run`` and ``probe`` hit the live portals; they are for manual checks, not pytest.
"""
from __future__ import annotations

import json
from dataclasses import asdict

import typer

from ..catalog import get_college_source
from ..cli import _json_default
from ..errors import SpecInvalid
from ..generic_replay import GenericReplayProvider
from ..providers import ScheduleProvider
from ..term import parse_term_label
from .registry import SPECS_DIR, load_all_specs, load_specs_from

app = typer.Typer(help="Replay-spec tools: validate, run one lookup, or probe every college.")


def _provider() -> ScheduleProvider:
    return GenericReplayProvider()


@app.callback()
def main() -> None:
    """Replay CLI command group."""


@app.command()
def validate() -> None:
    """Load every spec under src/schedule/data/specs strictly and report the first invalid one."""
    try:
        specs = load_specs_from(SPECS_DIR)
    except SpecInvalid as err:
        typer.echo(f"INVALID: {err}", err=True)
        raise typer.Exit(code=1) from err
    typer.echo(f"{len(specs)} spec(s) valid in {SPECS_DIR}")


@app.command()
def run(
    cc_id: int = typer.Option(..., help="Community college id with a replay spec."),
    term: str = typer.Option(..., help='Term label like "Fall 2026".'),
    course: str = typer.Option(..., help='Course code as ASSIST lists it, e.g. "MATH 400".'),
) -> None:
    """Run one live lookup through the college's replay spec and print the result as JSON."""
    if cc_id not in load_all_specs():
        raise typer.BadParameter(f"No replay spec for cc_id={cc_id}", param_hint="--cc-id")
    try:
        parsed_term = parse_term_label(term)
    except ValueError as err:
        raise typer.BadParameter(str(err), param_hint="--term") from err
    source = get_college_source(cc_id)
    out = _provider().search_course(source=source, term=parsed_term, course_code=course)
    typer.echo(json.dumps(asdict(out), indent=2, default=_json_default))


@app.command()
def probe(
    cc_id: int = typer.Option(0, help="Probe one college; 0 (default) probes every spec."),
) -> None:
    """Run each spec's recorded probe course and report PASS/FAIL per college."""
    specs = load_all_specs()
    if cc_id and cc_id not in specs:
        raise typer.BadParameter(f"No replay spec for cc_id={cc_id}", param_hint="--cc-id")
    targets = [specs[cc_id]] if cc_id else list(specs.values())
    provider = _provider()
    failures = 0
    for spec in targets:
        line = _probe_one(provider, spec)
        failures += line.startswith("FAIL")
        typer.echo(line)
    if failures:
        raise typer.Exit(code=1)


def _probe_one(provider: ScheduleProvider, spec) -> str:
    label = f"{spec.cc_id} {spec.cc_name}"
    try:
        out = provider.search_course(
            source=get_college_source(spec.cc_id),
            term=parse_term_label(spec.probe.term),
            course_code=spec.probe.course_code,
        )
    except Exception as err:  # a probe must report, not crash, so every college is listed
        return f"FAIL {label} {type(err).__name__}: {err}"
    rows = len(out.sections)
    if rows < spec.probe.expect_min_rows:
        return f"FAIL {label} {rows} row(s) (expected >= {spec.probe.expect_min_rows})"
    return f"PASS {label} {rows} row(s)"


if __name__ == "__main__":
    app()
