"""Print a Colleague Self-Service portal's term codes and location codes.

Usage:
    uv run python -m scripts.discover_colleague https://selfservice.sjeccd.edu [KEYWORD]

The output is JSON you paste into src/schedule/data/colleges.json `params` and
`locations`. This is read-only against the portal: one GET and one POST.
"""
from __future__ import annotations

import json
import re
import sys

import requests

from src.schedule.colleague_selfservice import extract_request_token

_UA = "Mozilla/5.0 (compatible; cc-course-finder discovery; +https://github.com/FYC23/CC-course-finder)"
_SEASON2 = {"fall": "FA", "spring": "SP", "summer": "SU"}
_SEASON1 = {"fall": "F", "spring": "S", "summer": "U"}


def suggest_term_format(value: str, description: str) -> str | None:
    """Infer a `term_format` template from one (code, label) pair, or None if no template fits."""
    match = re.match(r"^(Spring|Summer|Fall)\s+(\d{4})", description, re.IGNORECASE)
    if not match:
        return None
    season = match.group(1).lower()
    year = match.group(2)
    candidates = {
        "{yyyy}{SEASON2}": f"{year}{_SEASON2[season]}",
        "{yyyy}/{SEASON2}": f"{year}/{_SEASON2[season]}",
        "{yyyy}{SEASON1}": f"{year}{_SEASON1[season]}",
        "{yy}/{SEASON2}": f"{year[-2:]}/{_SEASON2[season]}",
        "{yy}{SEASON2}": f"{year[-2:]}{_SEASON2[season]}",
    }
    for template, rendered in candidates.items():
        if rendered == value:
            return template
    return None


def _filters(payload: dict, key: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for entry in payload.get(key) or []:
        if isinstance(entry, dict) and entry.get("Value"):
            out.append({
                "value": str(entry["Value"]),
                "description": str(entry.get("Description") or entry.get("Text") or ""),
            })
    return out


def discover(base_root: str, session: requests.Session, keyword: str = "MATH 1") -> dict:
    session.headers.setdefault("User-Agent", _UA)
    page = session.get(f"{base_root}/Student/Courses/Search", params={"keyword": keyword}, timeout=25)
    page.raise_for_status()
    token = extract_request_token(page.text)
    if token:
        session.headers["__RequestVerificationToken"] = token
    response = session.post(
        f"{base_root}/Student/Courses/PostSearchCriteria",
        json={"keyword": keyword, "pageNumber": 1, "quantityPerPage": 1,
              "searchResultsView": "CatalogListing", "terms": [], "locations": []},
        headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
        timeout=25,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    terms = _filters(payload, "TermFilters")
    suggested = next(
        (fmt for t in terms if (fmt := suggest_term_format(t["value"], t["description"]))), None
    )
    return {
        "base_root": base_root,
        "terms": terms,
        "locations": _filters(payload, "LocationFilters"),
        "suggested_term_format": suggested,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    keyword = argv[2] if len(argv) > 2 else "MATH 1"
    result = discover(argv[1].rstrip("/"), requests.Session(), keyword=keyword)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
