from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from src.assist import config
from src.assist.store import compute_options_hash, get_freshness, has_rows_for, query_rows
from src.schedule.composite import build_composite_provider
from src.schedule.service import ScheduleService
from src.schedule.term import parse_term_label

from ..join import join_results

router = APIRouter()

_service: ScheduleService | None = None
_service_db_path = None


def _get_service() -> ScheduleService:
    global _service, _service_db_path
    current_db_path = config.DB_PATH
    if _service is None or _service_db_path != current_db_path:
        _service = ScheduleService(db_path=current_db_path, provider=build_composite_provider())
        _service_db_path = current_db_path
    return _service


@router.get("/api/search")
async def search(
    response: Response,
    school: str = Query(...),
    major: str = Query(...),
    term: str = Query(...),
    cc_id: int | None = Query(default=None),
    requirement: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    try:
        parse_term_label(term)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err

    db_path = config.DB_PATH
    if not has_rows_for(db_path, school, major):
        raise HTTPException(
            status_code=409,
            detail=(
                "No ASSIST data for selected school/major. "
                "Run ingest first from Refresh ASSIST Data."
            ),
        )

    artic_rows = query_rows(db_path, school, major, requirement)

    loop = asyncio.get_event_loop()
    service = _get_service()
    try:
        schedule_results = await loop.run_in_executor(
            None,
            lambda: service.query(
                target_school=school,
                target_major=major,
                term_label=term,
                requirement_filter=requirement,
                cc_id=cc_id,
            ),
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    except Exception:
        schedule_results = []

    results = join_results(artic_rows, schedule_results)
    default_options_hash = compute_options_hash(config.DEFAULT_MAX_CC, False)
    freshness = get_freshness(db_path, school, major, default_options_hash)
    if freshness is not None:
        ingested_at = datetime.fromisoformat(freshness["ingested_at_utc"])
        if ingested_at.tzinfo is None:
            ingested_at = ingested_at.replace(tzinfo=timezone.utc)
        staleness_seconds = int(
            (datetime.now(tz=timezone.utc) - ingested_at).total_seconds()
        )
        response.headers["X-ASSIST-Staleness"] = str(max(0, staleness_seconds))

    return [
        {
            **{k: v for k, v in asdict(r).items() if k != "sections"},
            "sections": [asdict(s) for s in r.sections],
        }
        for r in results
    ]
