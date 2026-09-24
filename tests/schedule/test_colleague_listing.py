from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from unittest.mock import MagicMock

import pytest
import requests

from src.schedule.colleague_listing import listing_payload, parse_catalog_listing
from src.schedule.colleague_selfservice import ColleagueSelfServiceProvider
from src.schedule.errors import PortalChanged
from src.schedule.models import CollegeScheduleSource
from src.schedule.term import parse_term_label

_CATALOG = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "colleague" / "fcc_math_catalog.json").read_text()
)
_FRESNO = CollegeScheduleSource(
    cc_id=35, cc_name="Fresno City College", system="colleague_selfservice",
    base_url="https://selfservice.scccd.edu", locations=("FCC",),
    params=MappingProxyType({"term_format": "{yyyy}{SEASON2}"}),
)


def _resp(payload, text=""):
    r = MagicMock(spec=requests.Response)
    r.json.return_value = payload
    r.text = text
    r.url = "https://selfservice.scccd.edu/Student/Courses/PostSearchCriteria"
    r.raise_for_status = MagicMock()
    return r


def test_payload_asks_catalog_listing_for_one_subject():
    assert listing_payload(subject="MATH", term_code="2026FA", locations=("FCC",), page_number=2) == {
        "keyword": "", "subjects": ["MATH"], "pageNumber": 2, "quantityPerPage": 100,
        "searchResultsView": "CatalogListing", "terms": ["2026FA"], "locations": ["FCC"],
    }


def test_parse_catalog_listing():
    courses = parse_catalog_listing(_CATALOG)
    assert [(c.code, c.title) for c in courses] == [
        ("MATH 211S", "SUPPORT 4 STATS"), ("MATH 6", "MATH ANALYSIS III"),
        ("MATH C2210", "CALCULUS I"), ("MATH C2220", "CALCULUS II"),
    ]
    assert "(Formerly MATH 5B)" in courses[3].description


def test_parse_without_models_is_portal_changed():
    with pytest.raises(PortalChanged, match="CourseFullModels"):
        parse_catalog_listing({"Courses": []})


def test_list_subject_bootstraps_then_posts_each_page():
    session = MagicMock(spec=requests.Session)
    session.get.return_value = _resp({}, text="<html></html>")
    first = {**_CATALOG, "TotalPages": 2}
    second = {"CourseFullModels": [{"SubjectCode": "MATH", "Number": "4", "Title": "PRECAL ALGEBRA & TRIG",
                                    "Description": ""}], "TotalPages": 2}
    session.post.side_effect = [_resp(first), _resp(second)]
    courses = ColleagueSelfServiceProvider(session).list_subject(
        source=_FRESNO, term=parse_term_label("Fall 2026"), subject="math")
    assert [c.code for c in courses][-1] == "MATH 4" and len(courses) == 5
    payloads = [call.kwargs["json"] for call in session.post.call_args_list]
    assert [p["pageNumber"] for p in payloads] == [1, 2]
    assert payloads[0]["subjects"] == ["MATH"] and payloads[0]["terms"] == ["2026FA"]
