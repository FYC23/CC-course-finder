from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from src.assist import config
from src.assist.models import ArticulationRow
from src.assist.store import compute_options_hash, get_freshness, has_rows_for, query_rows
from src.schedule.composite import build_composite_provider
from src.schedule.fit import is_known_timezone
from src.schedule.service import QueryPlan, ScheduleService
from src.schedule.term import parse_term_label

from ..join import SearchResult, join_results
from ..serialize import section_to_dict

logger = logging.getLogger(__name__)

router = APIRouter()

_service: ScheduleService | None = None
_service_db_path = None

_TZ_QUERY = Query(default=None, max_length=64,
                  description="Student IANA timezone, e.g. Asia/Shanghai")
_STREAM_FAILED = "Schedule lookup failed partway through."


def _get_service() -> ScheduleService:
    global _service, _service_db_path
    current_db_path = config.DB_PATH
    if _service is None or _service_db_path != current_db_path:
        _service = ScheduleService(
            db_path=current_db_path, provider_factory=build_composite_provider
        )
        _service_db_path = current_db_path
    return _service


def _validate_request(
    school: str, major: str, term: str, requirement: str | None, tz: str | None
) -> list[ArticulationRow]:
    """Reject a bad request before any schedule lookup; return its articulation rows."""
    if tz is not None and not is_known_timezone(tz):
        raise HTTPException(status_code=422, detail=f"Unknown timezone: {tz!r}")
    try:
        parse_term_label(term)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    if not has_rows_for(config.DB_PATH, school, major):
        raise HTTPException(
            status_code=409,
            detail=(
                "No ASSIST data for selected school/major. "
                "Run ingest first from Refresh ASSIST Data."
            ),
        )
    return query_rows(config.DB_PATH, school, major, requirement)


def _set_staleness_header(response: Response, school: str, major: str) -> None:
    default_options_hash = compute_options_hash(config.DEFAULT_MAX_CC, False)
    freshness = get_freshness(config.DB_PATH, school, major, default_options_hash)
    if freshness is None:
        return
    ingested_at = datetime.fromisoformat(freshness["ingested_at_utc"])
    if ingested_at.tzinfo is None:
        ingested_at = ingested_at.replace(tzinfo=timezone.utc)
    staleness_seconds = int((datetime.now(tz=timezone.utc) - ingested_at).total_seconds())
    response.headers["X-ASSIST-Staleness"] = str(max(0, staleness_seconds))


def _result_dicts(results: list[SearchResult], tz: str | None) -> list[dict[str, Any]]:
    return [
        {
            **{k: v for k, v in asdict(r).items() if k != "sections"},
            "sections": [section_to_dict(s, student_tz=tz) for s in r.sections],
        }
        for r in results
    ]


@router.get("/api/search")
async def search(
    response: Response,
    school: str = Query(...),
    major: str = Query(...),
    term: str = Query(...),
    cc_id: int | None = Query(default=None),
    requirement: str | None = Query(default=None),
    tz: str | None = _TZ_QUERY,
) -> list[dict[str, Any]]:
    artic_rows = _validate_request(school, major, term, requirement, tz)

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
        logger.exception(
            "Schedule query failed for school=%r major=%r term=%r cc_id=%r",
            school,
            major,
            term,
            cc_id,
        )
        schedule_results = []

    _set_staleness_header(response, school, major)
    return _result_dicts(join_results(artic_rows, schedule_results), tz)


@router.get("/api/search/stream")
async def search_stream(
    school: str = Query(...),
    major: str = Query(...),
    term: str = Query(...),
    cc_id: int | None = Query(default=None),
    requirement: str | None = Query(default=None),
    tz: str | None = _TZ_QUERY,
) -> StreamingResponse:
    """Like /api/search, but sends newline-delimited JSON events as colleges finish:
    one "start" (total colleges, plus rows with no live schedule lookup), one "college"
    per finished college, then "done" -- or "error" if the lookup breaks partway."""
    artic_rows = _validate_request(school, major, term, requirement, tz)
    if cc_id is not None:
        artic_rows = [r for r in artic_rows if r.cc_id == cc_id]

    loop = asyncio.get_event_loop()
    service = _get_service()
    try:
        plan = await loop.run_in_executor(
            None,
            lambda: service.plan(
                target_school=school,
                target_major=major,
                term_label=term,
                requirement_filter=requirement,
                cc_id=cc_id,
            ),
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err

    response = StreamingResponse(
        _stream_events(service, plan, artic_rows, tz, request_label=(school, major, term)),
        media_type="application/x-ndjson",
    )
    _set_staleness_header(response, school, major)
    return response


def _stream_events(
    service: ScheduleService,
    plan: QueryPlan,
    artic_rows: list[ArticulationRow],
    tz: str | None,
    *,
    request_label: tuple[str, str, str],
) -> Iterator[str]:
    live_cc_ids = {college.source.cc_id for college in plan.colleges}
    rows_by_cc: dict[int, list[ArticulationRow]] = {}
    for row in artic_rows:
        rows_by_cc.setdefault(row.cc_id, []).append(row)
    offline_rows = [r for r in artic_rows if r.cc_id not in live_cc_ids]
    total = len(plan.colleges)

    yield _event(type="start", total=total,
                 results=_result_dicts(join_results(offline_rows, []), tz))
    done = 0
    results = service.iter_results(plan)
    try:
        for college in results:
            done += 1
            joined = join_results(rows_by_cc.get(college.cc_id, []), list(college.availabilities))
            yield _event(type="college", cc_id=college.cc_id, done=done, total=total,
                         results=_result_dicts(joined, tz))
    except Exception:
        logger.exception("Streaming schedule query failed for school=%r major=%r term=%r",
                         *request_label)
        yield _event(type="error", detail=_STREAM_FAILED)
        return
    finally:
        close = getattr(results, "close", None)
        if close is not None:
            close()
    yield _event(type="done", done=done, total=total)


def _event(**fields: Any) -> str:
    return json.dumps(fields) + "\n"
