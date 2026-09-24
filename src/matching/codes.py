"""Course-code spelling. Portals write the same course as 'MAT 1B', 'MAT-1B' or 'MAT1B', and
multi-word subjects like 'COMP SCI 1' exist; split_code finds subject and number, and
code_key gives one comparable key per course.

Known limit: a letter-prefixed number written with no separator ('MATHC2220') splits as
subject 'MATHC'. No portal or ASSIST row in this repo writes codes that way.
"""
from __future__ import annotations

import re

_CODE_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z&/.]*(?:\s+[A-Za-z][A-Za-z&/.]*)*?)\s*[- ]?\s*([A-Za-z]?\d[A-Za-z0-9]*)\s*$"
)
_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]")
_LEADING_ZEROS_RE = re.compile(r"^([A-Z]?)0+(?=\d)")


def split_code(code: str) -> tuple[str, str] | None:
    """('MATH', 'C2220') for 'MATH-C2220'; None when there is no subject and number."""
    match = _CODE_RE.match(code)
    if match is None:
        return None
    return " ".join(match.group(1).split()).upper(), match.group(2).upper()


def subject_key(subject: str) -> str:
    return _NON_ALNUM_RE.sub("", subject).upper()


def code_key(code: str) -> str:
    """'MAT|1B' for 'MAT 1B', 'MAT-1B' and 'MAT1B'; leading zeros in the number are dropped."""
    parts = split_code(code)
    if parts is None:
        return _NON_ALNUM_RE.sub("", code).upper()
    subject, number = parts
    trimmed = _LEADING_ZEROS_RE.sub(r"\1", number)
    return f"{subject_key(subject)}|{trimmed}"
