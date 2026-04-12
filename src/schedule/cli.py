from __future__ import annotations

import json
from dataclasses import asdict

import requests
import typer

from src.assist.config import DB_PATH

from .banner_ellucian import BannerEllucianProvider
from .catalog import get_college_source
from .models import CollegeScheduleSource, CourseAvailability
from .providers import ScheduleProvider
from .service import ScheduleService
from .term import ParsedTerm
from .wvm_static import WvmStaticProvider


class _CompositeProvider:
    def __init__(self, providers: list[ScheduleProvider]) -> None:
        self._providers = providers

    def supports_source(self, source: CollegeScheduleSource) -> bool:
        return any(p.supports_source(source) for p in self._providers)

    def search_course(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, course_code: str
    ) -> CourseAvailability:
        for p in self._providers:
            if p.supports_source(source):
                return p.search_course(source=source, term=term, course_code=course_code)
        raise ValueError(f"No provider for system={source.system!r}")

app = typer.Typer(help="Schedule layer query CLI.")


@app.callback()
def main() -> None:
    """Schedule CLI command group."""


@app.command()
def query(
    target_school: str = typer.Option(..., help="Target university name."),
    target_major: str = typer.Option(..., help="Target major label."),
    term: str = typer.Option(..., help='Canonical term label like "Summer 2026".'),
    requirement: str = typer.Option("", help="Optional requirement text filter."),
    cc_id: int = typer.Option(
        2,
        help=(
            "Community college id for configured schedule sources; "
            "default is Evergreen Valley College (2)."
        ),
    ),
) -> None:
    """Query schedule offerings for ASSIST course matches."""
    provider = _CompositeProvider([BannerEllucianProvider(), WvmStaticProvider()])
    try:
        source = get_college_source(cc_id)
    except KeyError as err:
        raise typer.BadParameter(str(err), param_hint="--cc-id") from err
    if not provider.supports_source(source):
        raise typer.BadParameter(
            f"No provider configured for source system={source.system!r} (cc_id={source.cc_id})",
            param_hint="--cc-id",
        )

    service = ScheduleService(db_path=DB_PATH, provider=provider)
    try:
        rows = service.query(
            target_school=target_school,
            target_major=target_major,
            term_label=term,
            requirement_filter=requirement or None,
            cc_id=cc_id,
        )
    except ValueError as err:
        typer.echo(f"Invalid input: {err}", err=True)
        raise typer.Exit(code=2) from err
    except requests.RequestException as err:
        typer.echo(f"Schedule request failed: {err}", err=True)
        raise typer.Exit(code=1) from err
    typer.echo(json.dumps([asdict(row) for row in rows], indent=2))


if __name__ == "__main__":
    app()
