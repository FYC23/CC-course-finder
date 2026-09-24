from __future__ import annotations

import pytest

from src.matching.codes import code_key, split_code, subject_key


@pytest.mark.parametrize("code, parts, key", [
    ("MAT 1B", ("MAT", "1B"), "MAT|1B"),
    ("MAT-1B", ("MAT", "1B"), "MAT|1B"),
    ("MAT1B", ("MAT", "1B"), "MAT|1B"),
    ("MATH-C2220", ("MATH", "C2220"), "MATH|C2220"),
    ("MATH C2220", ("MATH", "C2220"), "MATH|C2220"),
    ("COMP SCI 1", ("COMP SCI", "1"), "COMPSCI|1"),
    ("CS/IS 165", ("CS/IS", "165"), "CSIS|165"),
    ("ENGL 001B", ("ENGL", "001B"), "ENGL|1B"),
    ("MATH 070", ("MATH", "070"), "MATH|70"),
    ("MATH C285", ("MATH", "C285"), "MATH|C285"),
    ("STAT C1000", ("STAT", "C1000"), "STAT|C1000"),
    ("ENGL-C1000H", ("ENGL", "C1000H"), "ENGL|C1000H"),
    ("math 5a", ("MATH", "5A"), "MATH|5A"),
])
def test_split_and_key(code, parts, key):
    assert split_code(code) == parts
    assert code_key(code) == key


def test_unparseable_code_keys_to_its_alphanumerics():
    assert split_code("MATH") is None
    assert code_key("Math!") == "MATH"


def test_known_limit_letter_prefixed_number_without_separator():
    # Portals in this repo always separate subject and number; this spelling is not produced.
    assert split_code("MATHC2220") == ("MATHC", "2220")


def test_subject_key_ignores_spacing_and_punctuation():
    assert subject_key("Comp Sci") == subject_key("COMPSCI") == "COMPSCI"
