from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from .models import AgreementRef, ArticulationRow

_COURSE_PATTERN = re.compile(r"([A-Z]{2,16})\s*([0-9]{1,3}[A-Z]{0,2}(?:\+[0-9]{1,3}[A-Z]{0,2})*)")
# A line that is only a course code, e.g. "COM SCI M51A", "CS/IS 165", "MATH -04C", "ENGL 102 F".
_COURSE_LINE = re.compile(
    r"[A-Z][A-Z&/.]*(?: [A-Z][A-Z&/.]*)*(?: ?-)? ?-?[A-Z]?[0-9]{1,4}[A-Z]{0,3}(?: [A-Z]{1,2})?"
)
_UNITS_SUFFIX = re.compile(r"\([0-9]+(?:\.[0-9]+)?\)$")
_CAMPUS_MARKER = re.compile(r" [A-Z]$")
_MAX_TITLE_LINES = 4
_ZWSP = "\u200b"


def extract_text_from_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    chunks: list[str] = []
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
    text = "\n".join(chunks)
    return text


def _normalize_course_code(raw: str) -> str:
    normalized_raw = raw.replace(_ZWSP, " ")
    match = _COURSE_PATTERN.search(normalized_raw.upper())
    if not match:
        return normalized_raw.strip()
    return f"{match.group(1)} {match.group(2)}"


def _clean_line(line: str) -> str:
    return " ".join(line.replace(_ZWSP, " ").split()).upper()


def _is_course_line(line: str) -> bool:
    return _COURSE_LINE.fullmatch(_clean_line(line)) is not None


def _has_course(text: str) -> bool:
    return _is_course_line(text) or _COURSE_PATTERN.search(_clean_line(text)) is not None


def _normalize_uc_course(raw: str) -> str:
    """A UC course line keeps its whole department ("COM SCI 33"); requirement text falls back."""
    if _is_course_line(raw):
        return _clean_line(raw)
    return _normalize_course_code(raw)


def _normalize_cc_course(raw: str) -> str:
    """A CC course line is kept whole ("COMP SCI 1", "MATH 2400", "MATH C285").

    NOCCCD's trailing campus marker ("MATH 151 F") is dropped, as the older parser did.
    """
    if not _is_course_line(raw):
        return _normalize_course_code(raw)
    return _CAMPUS_MARKER.sub("", _clean_line(raw))


def _uc_block_line(lines: list[str], arrow: int) -> str:
    """The UC side of a lone arrow: the course line above its title, or a requirement sentence.

    Never looks past the title, so it cannot reach the previous block's CC courses or notes.
    """
    above = arrow - 1
    if above < 0:
        return ""
    if not _UNITS_SUFFIX.search(lines[above]):
        return lines[above]
    for title in range(above, max(above - _MAX_TITLE_LINES, 0), -1):
        if lines[title].startswith("-"):
            course = lines[title - 1]
            return course if _is_course_line(course) else ""
    return ""


def _cc_block_line(lines: list[str], arrow: int) -> str:
    """The CC side of a lone arrow: the line right after it, if that line is a course.

    "No Course Articulated" and "Course(s) Denied" mean there is no CC course, so the
    next UC block's course must not be borrowed.
    """
    below = arrow + 1
    if below < len(lines) and _is_course_line(lines[below]):
        return lines[below]
    return ""


def _cc_title(lines: list[str], course: int) -> str:
    """The title printed under a CC course line: "- Title (4.00)", sometimes wrapped onto
    the next lines before the units. Empty when there is no title block.

    A "---" separator line must never be mistaken for the start of a title block, so the
    first line must start with "-" but not with the "--" that opens a separator.
    """
    start = course + 1
    if start >= len(lines) or not lines[start].startswith("-") or lines[start].startswith("--"):
        return ""
    parts: list[str] = []
    for index in range(start, min(start + _MAX_TITLE_LINES, len(lines))):
        parts.append(" ".join(lines[index].replace(_ZWSP, " ").split()))
        if _UNITS_SUFFIX.search(lines[index]):
            break
    else:
        return ""
    text = " ".join(parts).removeprefix("-").strip()
    return _UNITS_SUFFIX.sub("", text).strip()


def _inline_candidates(lines: list[str]) -> list[tuple[str, str, str]]:
    """Lines with a left-right arrow marker or course-pair separator; inline layouts carry
    no title. Keeps the old precedence: the first separator found in each line wins."""
    candidates: list[tuple[str, str, str]] = []
    for line in lines:
        for separator in ("←", "→", "->", "=="):
            if separator in line:
                left, right = line.split(separator, 1)
                candidates.append((left.strip(), right.strip(), ""))
                break
    return candidates


def _lone_arrow_candidates(lines: list[str]) -> list[tuple[str, str, str]]:
    """Newer ASSIST PDFs place the arrow on its own line between the UC block and the CC
    block; the CC title, if any, follows the CC course line."""
    candidates: list[tuple[str, str, str]] = []
    for i, line in enumerate(lines):
        if line != "←":
            continue
        left_line = _uc_block_line(lines, i)
        right_line = _cc_block_line(lines, i)
        if left_line and right_line:
            candidates.append((left_line, right_line, _cc_title(lines, i + 1)))
    return candidates


def parse_articulation_rows(ref: AgreementRef, raw_text: str) -> list[ArticulationRow]:
    """Best-effort parser for early v1.

    This parser intentionally focuses on simple, direct mappings and preserves raw text
    for rows that can be manually audited later.
    """
    rows: list[ArticulationRow] = []
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

    # Each candidate is (UC side, CC side, CC title); inline layouts carry no title.
    candidate_pairs = _inline_candidates(lines) + _lone_arrow_candidates(lines)

    for left, right, title in candidate_pairs:
        source_line = f"{left} -> {right}"
        cc_course = _normalize_cc_course(right)
        uc_course = _normalize_uc_course(left)
        if not _has_course(right):
            continue

        rows.append(
            ArticulationRow(
                target_school=ref.target_school_name,
                target_major=ref.target_major,
                target_requirement=uc_course,
                uc_equivalent=uc_course,
                cc_name=ref.cc_name,
                cc_id=ref.cc_id,
                course_code=cc_course,
                course_title=title,
                agreement_id=ref.agreement_id,
                academic_year=ref.academic_year_label or str(ref.academic_year_id),
                source_url=ref.artifact_url,
                notes="parsed_with_v1_heuristic",
                raw_text=line_limit(source_line, 300),
            )
        )
    return rows


def line_limit(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...[truncated]"

