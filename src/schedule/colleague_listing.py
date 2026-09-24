"""Colleague Self-Service CatalogListing for one subject (every course, with descriptions)."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import requests

from .errors import PortalChanged
from .listing import ListedCourse, unique_courses
from .normalize import int_or_none

_PAGE_SIZE = 100
_MAX_LISTING_PAGES = 5


def listing_payload(
    *, subject: str, term_code: str, locations: tuple[str, ...], page_number: int
) -> dict[str, object]:
    return {
        "keyword": "",
        "subjects": [subject],
        "pageNumber": page_number,
        "quantityPerPage": _PAGE_SIZE,
        "searchResultsView": "CatalogListing",
        "terms": [term_code],
        "locations": list(locations),
    }


def parse_catalog_listing(payload: Mapping[str, Any]) -> tuple[ListedCourse, ...]:
    models = payload.get("CourseFullModels")
    if not isinstance(models, list):
        raise PortalChanged("Colleague CatalogListing reply has no CourseFullModels list")
    courses: list[ListedCourse] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        subject = str(model.get("SubjectCode") or "").strip()
        number = str(model.get("Number") or "").strip()
        if subject and number:
            courses.append(ListedCourse(
                code=f"{subject} {number}",
                title=str(model.get("Title") or "").strip(),
                description=str(model.get("Description") or "").strip(),
            ))
    return tuple(courses)


def fetch_subject_listing(
    session: requests.Session,
    *,
    search_url: str,
    subject: str,
    term_code: str,
    locations: tuple[str, ...],
    headers: Mapping[str, str],
) -> tuple[ListedCourse, ...]:
    courses: list[ListedCourse] = []
    page = 1
    while True:
        response = session.post(
            search_url,
            json=listing_payload(subject=subject, term_code=term_code, locations=locations, page_number=page),
            headers=dict(headers),
            timeout=20,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as err:
            raise PortalChanged(f"Colleague CatalogListing reply is not JSON: {err}") from err
        courses.extend(parse_catalog_listing(payload))
        total_pages = int_or_none(payload.get("TotalPages")) or 1
        if page >= min(total_pages, _MAX_LISTING_PAGES):
            return unique_courses(courses)
        page += 1
