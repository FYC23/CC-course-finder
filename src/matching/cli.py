"""Course alias tools.

    uv run python -m src.matching.cli review                 # aliases waiting for a human
    uv run python -m src.matching.cli approve 12             # or: reject 12
    uv run python -m src.matching.cli add --cc-id 35 --old "MATH 7" --new "MATH 17" --evidence "..."
    uv run python -m src.matching.cli discover --cc-id 35 --term "Fall 2026"   # live; uses DECISION_PROVIDER
    uv run python -m src.matching.cli export                 # verified DB rows -> committed seed file
    uv run python -m src.matching.cli import-rccd --html saved-page.html

`discover` hits live portals and, when DECISION_PROVIDER is set, a decision backend.
"""
from __future__ import annotations

import csv
from collections import Counter
from datetime import date
from pathlib import Path

import requests
import typer

from src.assist.config import DB_PATH
from src.assist.store import ensure_db, query_rows
from src.decisions.factory import decision_provider_from_env
from src.decisions.types import DecisionUnavailable
from src.llm.errors import LlmError
from src.schedule.catalog import get_college_source
from src.schedule.composite import build_composite_provider
from src.schedule.errors import ScheduleLookupError
from src.schedule.term import TermNotListedError, parse_term_label

from .codes import split_code
from .discover import AssistCourse, DiscoverOutcome, discover_aliases
from .models import CourseAlias
from .resolve import load_resolver
from .seeds import ALIASES_FILE, load_seed_aliases
from .sources.rccd import parse_rccd_crosswalk, seed_csv
from .store import list_aliases, review_alias, upsert_alias

app = typer.Typer(help="Course alias tools: review queue, discover pass, and seed maintenance.")
_DEFAULT_SCHOOL = "University of California, Los Angeles"
_DEFAULT_MAJOR = "Computer Science"


def _db_option() -> Path:
    return typer.Option(DB_PATH, "--db", help="SQLite database (default: data/assist.sqlite3).")


def _line(alias: CourseAlias) -> str:
    return (
        f"#{alias.alias_id} [{alias.status}] cc={alias.cc_id} {alias.old_code} -> {alias.new_code} "
        f"({alias.source}, p={alias.confidence:.2f}) {alias.evidence}"
    ).rstrip()


@app.callback()
def main() -> None:
    """Matching CLI command group."""


@app.command("list")
def list_command(
    cc_id: int = typer.Option(0, help="Only this college (0 = all)."),
    status: str = typer.Option("", help="Only this status: verified, accepted, review, rejected."),
    db: Path = _db_option(),
) -> None:
    """Print stored aliases."""
    aliases = list_aliases(db, cc_id=cc_id or None, statuses=(status,) if status else None)
    for alias in aliases:
        typer.echo(_line(alias))
    typer.echo(f"{len(aliases)} alias(es)")


@app.command()
def review(cc_id: int = typer.Option(0, help="Only this college (0 = all)."), db: Path = _db_option()) -> None:
    """Print aliases waiting for a human decision."""
    pending = list_aliases(db, cc_id=cc_id or None, statuses=("review",))
    if not pending:
        typer.echo("No aliases waiting for review.")
        return
    for alias in pending:
        typer.echo(_line(alias))
    typer.echo("Approve with: matching approve ID    Reject with: matching reject ID")


def _review(alias_id: int, db: Path, *, approve: bool) -> None:
    try:
        alias = review_alias(db, alias_id, approve=approve)
    except KeyError as err:
        typer.echo(str(err).strip("'\""), err=True)
        raise typer.Exit(code=1) from err
    typer.echo(_line(alias))


@app.command()
def approve(alias_id: int = typer.Argument(..., help="Alias id from `review`."), db: Path = _db_option()) -> None:
    """Approve an alias: it becomes verified and is used at query time."""
    _review(alias_id, db, approve=True)


@app.command()
def reject(alias_id: int = typer.Argument(..., help="Alias id from `review`."), db: Path = _db_option()) -> None:
    """Reject an alias: it is never used, and it blocks the same pair from the seeds."""
    _review(alias_id, db, approve=False)


@app.command()
def add(
    cc_id: int = typer.Option(..., help="Community college id."),
    old: str = typer.Option(..., help='ASSIST code, e.g. "MATH 7".'),
    new: str = typer.Option(..., help='Code the college lists now, e.g. "MATH 17".'),
    evidence: str = typer.Option(..., help="Where this mapping comes from."),
    db: Path = _db_option(),
) -> None:
    """Add a verified alias by hand."""
    try:
        get_college_source(cc_id)
    except KeyError as err:
        raise typer.BadParameter(str(err), param_hint="--cc-id") from err
    for value, hint in ((old, "--old"), (new, "--new")):
        if split_code(value) is None:
            raise typer.BadParameter(f"{value!r} is not a course code", param_hint=hint)
    alias = CourseAlias(cc_id=cc_id, old_code=old, new_code=new, source="manual", status="verified",
                        confidence=1.0, evidence=evidence, reviewed=True)
    typer.echo(f"{upsert_alias(db, alias)}: {old} -> {new}")


def _assist_courses(db: Path, school: str, major: str, cc_id: int) -> tuple[AssistCourse, ...]:
    ensure_db(db)
    by_code: dict[str, AssistCourse] = {}
    for row in query_rows(db, school, major):
        if row.cc_id != cc_id:
            continue
        current = by_code.get(row.course_code)
        if current is None or (not current.title and row.course_title):
            by_code[row.course_code] = AssistCourse(row.course_code, row.course_title, row.uc_equivalent)
    return tuple(by_code.values())


def _report(outcome: DiscoverOutcome, db: Path) -> None:
    note = f" ({outcome.note})" if outcome.note else ""
    typer.echo(f"{outcome.course_code}: {outcome.status}{note}")
    for alias in outcome.aliases:
        result = upsert_alias(db, alias)
        typer.echo(f"   {result}: {alias.old_code} -> {alias.new_code} [{alias.status}, p={alias.confidence:.2f}]")


@app.command()
def discover(
    cc_id: int = typer.Option(..., help="Community college id."),
    term: str = typer.Option(..., help='Term label like "Fall 2026".'),
    target_school: str = typer.Option(_DEFAULT_SCHOOL, help="ASSIST target school."),
    target_major: str = typer.Option(_DEFAULT_MAJOR, help="ASSIST target major."),
    db: Path = _db_option(),
) -> None:
    """Find this term's codes for one college's ASSIST courses (live; see module docstring)."""
    try:
        source = get_college_source(cc_id)
    except KeyError as err:
        raise typer.BadParameter(str(err), param_hint="--cc-id") from err
    try:
        parsed_term = parse_term_label(term)
    except ValueError as err:
        raise typer.BadParameter(str(err), param_hint="--term") from err
    courses = _assist_courses(db, target_school, target_major, cc_id)
    if not courses:
        typer.echo(f"No ASSIST rows for cc_id={cc_id} ({target_school} / {target_major}); run ingest first.", err=True)
        raise typer.Exit(code=1)
    try:
        decider = decision_provider_from_env()
    except (LlmError, DecisionUnavailable, ValueError) as err:
        typer.echo(f"Decision backend misconfigured: {err}", err=True)
        raise typer.Exit(code=2) from err
    known = frozenset((a.cc_id, a.old_key, a.new_key) for a in list_aliases(db, cc_id=cc_id))
    try:
        outcomes = discover_aliases(source=source, term=parsed_term, courses=courses,
                                    lister=build_composite_provider(), resolver=load_resolver(db),
                                    decider=decider, known_pairs=known)
    except TermNotListedError as err:
        typer.echo(f"{term} is not listed on the college's schedule site: {err}", err=True)
        raise typer.Exit(code=1) from err
    except (requests.RequestException, ScheduleLookupError) as err:
        typer.echo(f"{source.cc_name}: {type(err).__name__}: {err}", err=True)
        raise typer.Exit(code=1) from err
    for outcome in outcomes:
        _report(outcome, db)
    counts = Counter(outcome.status for outcome in outcomes)
    typer.echo("Summary: " + ", ".join(f"{status}={n}" for status, n in sorted(counts.items())))


@app.command()
def export(db: Path = _db_option(), out: Path = typer.Option(ALIASES_FILE, help="Seed CSV to append to.")) -> None:
    """Append verified database aliases that the seed file lacks, so they survive a fresh clone."""
    seeded = {(a.cc_id, a.old_key, a.new_key) for a in load_seed_aliases(out)}
    fresh = [a for a in list_aliases(db, statuses=("verified",)) if (a.cc_id, a.old_key, a.new_key) not in seeded]
    with out.open("a", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        for alias in fresh:
            writer.writerow([alias.cc_id, alias.old_code, alias.new_code, alias.source, alias.evidence])
    typer.echo(f"{len(fresh)} alias(es) appended to {out}")


@app.command("import-rccd")
def import_rccd(
    html: Path = typer.Option(..., exists=True, dir_okay=False, help="Saved copy of rccd.edu/commoncoursenumbering."),
    checked_on: str = typer.Option(date.today().isoformat(), help="Date the page was saved (YYYY-MM-DD)."),
) -> None:
    """Print seed rows for src/matching/data/course_aliases.csv from a saved RCCD page."""
    typer.echo(seed_csv(parse_rccd_crosswalk(html.read_text()), checked_on=checked_on), nl=False)


if __name__ == "__main__":
    app()
