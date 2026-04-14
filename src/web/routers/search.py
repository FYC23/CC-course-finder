from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.assist.config import DB_PATH
from src.assist.store import query_rows
from src.schedule.composite import build_composite_provider
from src.schedule.service import ScheduleService
from src.schedule.term import parse_term_label

from ..join import join_results

router = APIRouter()

_service: ScheduleService | None = None


def _get_service() -> ScheduleService:
    global _service
    if _service is None:
        _service = ScheduleService(db_path=DB_PATH, provider=build_composite_provider())
    return _service


@router.get("/api/search")
async def search(
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

    artic_rows = query_rows(DB_PATH, school, major, requirement)

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
    return [
        {
            **{k: v for k, v in asdict(r).items() if k != "sections"},
            "sections": [asdict(s) for s in r.sections],
        }
        for r in results
    ]
