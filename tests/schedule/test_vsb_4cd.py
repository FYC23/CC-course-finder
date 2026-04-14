"""Tests for Vsb4cdProvider."""
from __future__ import annotations

from unittest.mock import MagicMock
import pytest
import requests

from src.schedule.vsb_4cd import Vsb4cdProvider, _term_code, _course_key
from src.schedule.models import CollegeScheduleSource
from src.schedule.term import parse_term_label

_LMC = CollegeScheduleSource(
    cc_id=61,
    cc_name="Los Medanos College",
    system="vsb_4cd",
    base_url="https://vsb.4cd.edu",
    locations=("LMC",),
)

_BANNER = CollegeScheduleSource(
    cc_id=2,
    cc_name="Evergreen Valley College",
    system="banner",
    base_url="https://colss-prod.ec.sjeccd.edu/Student/Courses/SearchResult",
    locations=("EVC",),
)

_XML_TWO_SECTIONS = """\
<addcourse>
<errors></errors>
<classdata date="1776012666786">
 <campus n="LMC" v="LMC"/>
 <course key="MATH-220" code="MATH" number="220">
  <uselection key="--202610_1001--">
   <selection key="--202610_1001--" thc="Calculus II">
    <block type="02" key="1001" secNo="7011" isFull="0" os="5" im="03" teacher="D. Freeland" campus="LMC"/>
   </selection>
  </uselection>
  <uselection key="--202610_1002--">
   <selection key="--202610_1002--" thc="Calculus II">
    <block type="Lecture" key="1002" secNo="7407" isFull="1" os="0" im="01" teacher="J. Cohen" campus="LMC"/>
   </selection>
  </uselection>
 </course>
</classdata>
</addcourse>"""

_XML_EMPTY = """\
<addcourse>
<errors></errors>
<classdata date="1776012666786">
 <course key="MATH-999" code="MATH" number="999">
 </course>
</classdata>
</addcourse>"""

_XML_WRONG_CAMPUS = """\
<addcourse>
<errors></errors>
<classdata date="1776012666786">
 <course key="MATH-220" code="MATH" number="220">
  <uselection key="--202610_2001--">
   <selection key="--202610_2001--" thc="Calculus II">
    <block type="02" key="2001" secNo="9001" isFull="0" os="3" im="03" teacher="N. Crawford" campus="DVC"/>
   </selection>
  </uselection>
 </course>
</classdata>
</addcourse>"""


def _make_resp(text: str, status: int = 200) -> MagicMock:
    r = MagicMock(spec=requests.Response)
    r.status_code = status
    r.text = text
    r.url = "https://vsb.4cd.edu/api/class-data"
    r.raise_for_status = MagicMock()
    return r


def _make_session(xml: str = _XML_TWO_SECTIONS) -> MagicMock:
    s = MagicMock(spec=requests.Session)
    s.headers = {}
    s.get.return_value = _make_resp(xml)
    return s


# ---------------------------------------------------------------------------
# _term_code
# ---------------------------------------------------------------------------

def test_term_code_summer():
    assert _term_code(parse_term_label("Summer 2026")) == "202610"


def test_term_code_fall():
    assert _term_code(parse_term_label("Fall 2026")) == "202620"


def test_term_code_spring():
    assert _term_code(parse_term_label("Spring 2026")) == "202630"


# ---------------------------------------------------------------------------
# _course_key
# ---------------------------------------------------------------------------

def test_course_key_space():
    assert _course_key("MATH 220") == "MATH-220"


def test_course_key_already_hyphen():
    assert _course_key("MATH-220") == "MATH-220"


# ---------------------------------------------------------------------------
# supports_source
# ---------------------------------------------------------------------------

def test_supports_vsb_4cd():
    assert Vsb4cdProvider().supports_source(_LMC)


def test_rejects_banner():
    assert not Vsb4cdProvider().supports_source(_BANNER)


# ---------------------------------------------------------------------------
# search_course — happy path
# ---------------------------------------------------------------------------

def test_search_course_returns_sections():
    s = _make_session(_XML_TWO_SECTIONS)
    p = Vsb4cdProvider(session=s)
    term = parse_term_label("Summer 2026")
    result = p.search_course(source=_LMC, term=term, course_code="MATH 220")
    assert result.offered is True
    assert len(result.sections) == 2
    assert result.sections[0].section_id == "7011"
    assert result.sections[0].status == "open"
    assert result.sections[0].modality == "in-person"
    assert result.sections[1].section_id == "7407"
    assert result.sections[1].status == "closed"
    assert result.sections[1].modality == "online"


def test_search_course_empty_returns_not_offered():
    s = _make_session(_XML_EMPTY)
    p = Vsb4cdProvider(session=s)
    term = parse_term_label("Summer 2026")
    result = p.search_course(source=_LMC, term=term, course_code="MATH 999")
    assert result.offered is False
    assert result.sections == []


def test_search_course_filters_by_campus():
    s = _make_session(_XML_WRONG_CAMPUS)
    p = Vsb4cdProvider(session=s)
    term = parse_term_label("Summer 2026")
    result = p.search_course(source=_LMC, term=term, course_code="MATH 220")
    assert result.offered is False
    assert result.sections == []


def test_search_course_sets_metadata():
    s = _make_session(_XML_TWO_SECTIONS)
    p = Vsb4cdProvider(session=s)
    term = parse_term_label("Summer 2026")
    result = p.search_course(source=_LMC, term=term, course_code="MATH 220")
    assert result.cc_id == 61
    assert result.cc_name == "Los Medanos College"
    assert result.term == "Summer 2026"
    assert result.course_code == "MATH 220"


def test_search_course_raises_for_wrong_system():
    p = Vsb4cdProvider()
    term = parse_term_label("Summer 2026")
    with pytest.raises(ValueError, match="does not support"):
        p.search_course(source=_BANNER, term=term, course_code="MATH 220")
