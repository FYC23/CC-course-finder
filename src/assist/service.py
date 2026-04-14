from __future__ import annotations

from datetime import datetime, timezone

from src.assist.discovery import AssistDiscovery
from src.assist.fetch import ArtifactFetcher
from src.assist.http import AssistHttpClient
from src.assist.pipeline import ingest_target_major
from src.assist.store import (
    DB_PATH,
    compute_options_hash,
    update_job,
    upsert_freshness,
)


def run_ingest_job(
    job_id: str,
    school: str,
    major: str,
    max_cc: int | None,
    allow_non_numeric_keys: bool,
) -> None:
    started_at = datetime.now(tz=timezone.utc).isoformat()
    update_job(DB_PATH, job_id, status="running", started_at_utc=started_at)
    try:
        client = AssistHttpClient()
        discovery = AssistDiscovery(
            client=client,
            allow_non_numeric_keys=allow_non_numeric_keys,
        )
        fetcher = ArtifactFetcher(client=client)
        run = ingest_target_major(
            discovery=discovery,
            fetcher=fetcher,
            db_path=DB_PATH,
            target_school=school,
            major_name=major,
            max_community_colleges=max_cc,
            allow_non_numeric_keys=allow_non_numeric_keys,
        )
        completed_at = datetime.now(tz=timezone.utc).isoformat()
        update_job(
            DB_PATH,
            job_id,
            status="completed",
            completed_at_utc=completed_at,
            run_id=run.run_id,
            rows_written=run.rows_written,
            agreements_seen=run.agreements_seen,
        )
        options_hash = compute_options_hash(max_cc, allow_non_numeric_keys)
        upsert_freshness(
            DB_PATH,
            school,
            major,
            options_hash,
            run,
            max_cc,
            allow_non_numeric_keys,
        )
    except Exception as exc:
        completed_at = datetime.now(tz=timezone.utc).isoformat()
        update_job(
            DB_PATH,
            job_id,
            status="failed",
            completed_at_utc=completed_at,
            error_message=f"{type(exc).__name__}: {exc}",
        )
