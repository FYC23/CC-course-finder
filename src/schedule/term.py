from __future__ import annotations

from dataclasses import dataclass
import re

_TERM_LABEL_RE = re.compile(r"^(Spring|Summer|Fall) ([0-9]{4})$")


@dataclass(frozen=True)
class ParsedTerm:
    label: str
    season: str
    year: int


def parse_term_label(label: str) -> ParsedTerm:
    match = _TERM_LABEL_RE.match(label)
    if not match:
        raise ValueError(
            "Invalid term label. Expected format like 'Summer 2026' with Spring/Summer/Fall."
        )
    season, year_text = match.groups()
    return ParsedTerm(label=label, season=season.lower(), year=int(year_text))
