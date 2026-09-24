from __future__ import annotations

from bs4 import BeautifulSoup

from src.schedule.replay.text import element_text, stringify


def test_stringify_none_and_false_are_empty():
    assert stringify(None) == ""
    assert stringify(False) == ""


def test_stringify_true_is_lowercase_true():
    assert stringify(True) == "true"


def test_stringify_integral_float_drops_decimal():
    assert stringify(42.0) == "42"


def test_stringify_non_integral_float_keeps_decimal():
    assert stringify(42.5) == "42.5"


def test_stringify_strips_whitespace():
    assert stringify(" x ") == "x"


def _tag(html: str):
    return BeautifulSoup(html, "html.parser").find()


def test_element_text_collapses_whitespace():
    element = _tag("<div>  a\nb   c </div>")
    assert element_text(element) == "a b c"


def test_element_text_attr():
    element = _tag("<a href='/x'>n</a>")
    assert element_text(element, "href") == "/x"


def test_element_text_multi_valued_class_attr_is_space_joined():
    element = _tag("<a class='foo bar'>n</a>")
    assert element_text(element, "class") == "foo bar"


def test_element_text_missing_attr_is_empty():
    element = _tag("<a>n</a>")
    assert element_text(element, "href") == ""
