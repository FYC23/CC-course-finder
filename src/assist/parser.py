from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from .models import AgreementRef, ArticulationRow

_COURSE_PATTERN = re.compile(r"([A-Z]{2,16})\s*([0-9]{1,3}[A-Z]{0,2}(?:\+[0-9]{1,3}[A-Z]{0,2})*)")


def extract_text_from_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    chunks: list[str] = []
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
    text = "\n".join(chunks)
    return text


def _normalize_course_code(raw: str) -> str:
    normalized_raw = raw.replace("\u200b", " ")
    match = _COURSE_PATTERN.search(normalized_raw.upper())
    if not match:
        return normalized_raw.strip()
    return f"{match.group(1)} {match.group(2)}"


def parse_articulation_rows(ref: AgreementRef, raw_text: str) -> list[ArticulationRow]:
    """Best-effort parser for early v1.

    This parser intentionally focuses on simple, direct mappings and preserves raw text
    for rows that can be manually audited later.
    """
    rows: list[ArticulationRow] = []
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

    # Heuristic: look for lines with a left-right arrow marker or course-pair separators.
    candidate_pairs: list[tuple[str, str]] = []
    for line in lines:
        if "←" in line:
            left, right = line.split("←", 1)
            candidate_pairs.append((left.strip(), right.strip()))
        elif "→" in line:
            left, right = line.split("→", 1)
            candidate_pairs.append((left.strip(), right.strip()))
        elif "->" in line:
            left, right = line.split("->", 1)
            candidate_pairs.append((left.strip(), right.strip()))
        elif "==" in line:
            left, right = line.split("==", 1)
            candidate_pairs.append((left.strip(), right.strip()))

    # Heuristic: newer ASSIST PDFs often place the arrow on its own line.
    for i, line in enumerate(lines):
        if line != "←":
            continue
        left_line = ""
        right_line = ""
        for j in range(i - 1, -1, -1):
            if _COURSE_PATTERN.search(lines[j].replace("\u200b", " ").upper()):
                left_line = lines[j]
                break
        for j in range(i + 1, len(lines)):
            if _COURSE_PATTERN.search(lines[j].replace("\u200b", " ").upper()):
                right_line = lines[j]
                break
        if left_line and right_line:
            candidate_pairs.append((left_line.strip(), right_line.strip()))

    for left, right in candidate_pairs:
        source_line = f"{left} -> {right}"
        cc_course = _normalize_course_code(right)
        uc_course = _normalize_course_code(left)
        if cc_course == right and uc_course == left:
            # Skip pairs where we found no course-like tokens.
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
                course_title="",
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

