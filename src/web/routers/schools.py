from __future__ import annotations

from fastapi import APIRouter, Query

from src.assist.config import DB_PATH
from src.assist.store import query_majors, query_schools

router = APIRouter()


@router.get("/api/schools")
def get_schools() -> list[str]:
    return query_schools(DB_PATH)


@router.get("/api/majors")
def get_majors(school: str = Query(...)) -> list[str]:
    return query_majors(DB_PATH, school)
