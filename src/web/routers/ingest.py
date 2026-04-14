from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.assist.config import DB_PATH
from src.assist.service import run_ingest_job
from src.assist.store import (
    _find_active_job,
    compute_options_hash,
    create_job,
    ensure_db,
    get_freshness,
    get_job,
    has_rows_for,
)

router = APIRouter()


class IngestOptions(BaseModel):
    max_cc: int | None = 8
    allow_non_numeric_keys: bool = False


class IngestStartRequest(BaseModel):
    target_school: str
    target_major: str
    options: IngestOptions = Field(default_factory=IngestOptions)


class IngestStartResponse(BaseModel):
    job_id: str
    message: str


class IngestStatusResponse(BaseModel):
    job_id: str
    status: str
    created_at_utc: str
    started_at_utc: str | None
    completed_at_utc: str | None
    agreements_seen: int
    rows_written: int
    error_message: str | None


class FreshnessData(BaseModel):
    ingested_at_utc: str
    agreements_seen: int
    rows_written: int
    staleness_seconds: int
    staleness_label: str


class IngestCheckResponse(BaseModel):
    rows_exist: bool
    freshness: FreshnessData | None


def _format_staleness(seconds: int) -> str:
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} hr ago"
    days = seconds // 86400
    suffix = "s" if days > 1 else ""
    return f"{days} day{suffix} ago"


def _build_freshness_response(
    school: str,
    major: str,
    max_cc: int | None,
    allow_non_numeric_keys: bool,
) -> FreshnessData | None:
    options_hash = compute_options_hash(max_cc, allow_non_numeric_keys)
    row = get_freshness(DB_PATH, school, major, options_hash)
    if row is None:
        return None
    ingested_at = datetime.fromisoformat(row["ingested_at_utc"])
    if ingested_at.tzinfo is None:
        ingested_at = ingested_at.replace(tzinfo=timezone.utc)
    seconds = max(0, int((datetime.now(tz=timezone.utc) - ingested_at).total_seconds()))
    return FreshnessData(
        ingested_at_utc=row["ingested_at_utc"],
        agreements_seen=int(row.get("agreements_seen", 0) or 0),
        rows_written=int(row.get("rows_written", 0) or 0),
        staleness_seconds=seconds,
        staleness_label=_format_staleness(seconds),
    )


@router.post("/api/ingest", response_model=IngestStartResponse)
async def start_ingest(payload: IngestStartRequest) -> IngestStartResponse:
    ensure_db(DB_PATH)
    active = _find_active_job(DB_PATH, payload.target_school, payload.target_major)
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"Ingest already running (job_id={active['job_id']}).",
        )

    job_id = str(uuid4())
    create_job(
        DB_PATH,
        job_id,
        payload.target_school,
        payload.target_major,
        payload.options.max_cc,
        payload.options.allow_non_numeric_keys,
    )

    from src.web.app import get_executor

    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        get_executor(),
        run_ingest_job,
        job_id,
        payload.target_school,
        payload.target_major,
        payload.options.max_cc,
        payload.options.allow_non_numeric_keys,
    )
    return IngestStartResponse(job_id=job_id, message="Ingest job started.")


@router.get("/api/ingest/status/{job_id}", response_model=IngestStatusResponse)
def ingest_status(job_id: str) -> IngestStatusResponse:
    ensure_db(DB_PATH)
    job = get_job(DB_PATH, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Ingest job not found.")
    return IngestStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        created_at_utc=job["created_at_utc"],
        started_at_utc=job["started_at_utc"],
        completed_at_utc=job["completed_at_utc"],
        agreements_seen=int(job.get("agreements_seen", 0) or 0),
        rows_written=int(job.get("rows_written", 0) or 0),
        error_message=job.get("error_message"),
    )


@router.get("/api/ingest/freshness", response_model=FreshnessData)
def ingest_freshness(
    school: str = Query(...),
    major: str = Query(...),
    max_cc: int | None = Query(default=8),
    allow_non_numeric_keys: bool = Query(default=False),
) -> FreshnessData:
    ensure_db(DB_PATH)
    freshness = _build_freshness_response(
        school,
        major,
        max_cc,
        allow_non_numeric_keys,
    )
    if freshness is None:
        raise HTTPException(status_code=404, detail="Freshness not found.")
    return freshness


@router.get("/api/ingest/check", response_model=IngestCheckResponse)
def ingest_check(
    school: str = Query(...),
    major: str = Query(...),
    max_cc: int | None = Query(default=8),
    allow_non_numeric_keys: bool = Query(default=False),
) -> IngestCheckResponse:
    ensure_db(DB_PATH)
    return IngestCheckResponse(
        rows_exist=has_rows_for(DB_PATH, school, major),
        freshness=_build_freshness_response(
            school,
            major,
            max_cc,
            allow_non_numeric_keys,
        ),
    )
