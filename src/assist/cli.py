from __future__ import annotations

import json

import typer

from .config import DB_PATH, DEFAULT_MAX_CC
from .discovery import AssistDiscovery
from .fetch import ArtifactFetcher
from .http import AssistHttpClient
from .pipeline import ingest_target_major
from .store import ensure_db, query_rows

app = typer.Typer(help="ASSIST layer ingestion/query CLI.")


def _build_services(
    api_prefix: str, allow_non_numeric_keys: bool = False
) -> tuple[AssistDiscovery, ArtifactFetcher]:
    client = AssistHttpClient(api_prefix=api_prefix)
    discovery = AssistDiscovery(
        client=client, allow_non_numeric_keys=allow_non_numeric_keys
    )
    fetcher = ArtifactFetcher(client=client)
    return discovery, fetcher


@app.command()
def ingest(
    target_school: str = typer.Option(..., help="Target university name (e.g. UCLA)."),
    target_major: str = typer.Option(..., help="Target major label on ASSIST."),
    api_prefix: str = typer.Option(
        "/api",
        help="ASSIST API prefix. Override if ASSIST changes API routing.",
    ),
    max_cc: int = typer.Option(
        DEFAULT_MAX_CC,
        help=(
            "Max unique community colleges to ingest for this run "
            "(v1 safety guard)."
        ),
    ),
    allow_non_numeric_keys: bool = typer.Option(
        False,
        help=(
            "Allow path-like agreement keys. Experimental: many currently fail "
            "when fetched from /api/artifacts."
        ),
    ),
) -> None:
    """Run a single ASSIST ingest for one target-major slice."""
    discovery, fetcher = _build_services(
        api_prefix=api_prefix, allow_non_numeric_keys=allow_non_numeric_keys
    )
    run = ingest_target_major(
        discovery=discovery,
        fetcher=fetcher,
        db_path=DB_PATH,
        target_school=target_school,
        major_name=target_major,
        max_community_colleges=max_cc,
        allow_non_numeric_keys=allow_non_numeric_keys,
        log=lambda message: typer.echo(message, err=True),
    )
    typer.echo(
        f"Ingest run {run.run_id}: agreements_seen={run.agreements_seen}, rows_written={run.rows_written}"
    )


@app.command()
def query(
    target_school: str = typer.Option(..., help="Target university name."),
    target_major: str = typer.Option(..., help="Target major label."),
    requirement: str = typer.Option("", help="Optional requirement text filter."),
) -> None:
    """Query locally stored ASSIST articulation rows."""
    ensure_db(DB_PATH)
    rows = query_rows(
        DB_PATH,
        target_school=target_school,
        target_major=target_major,
        requirement_filter=requirement or None,
    )
    payload = [row.__dict__ for row in rows]
    typer.echo(json.dumps(payload, indent=2))


if __name__ == "__main__":
    app()

