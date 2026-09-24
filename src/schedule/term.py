from __future__ import annotations

from dataclasses import dataclass
import re

_TERM_LABEL_RE = re.compile(r"^(Spring|Summer|Fall) ([0-9]{4})$")


class TermNotListedError(ValueError):
    """The college's schedule site does not list the requested term (not published yet,
    or already taken down), so its courses cannot be checked."""


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


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def term_match_rank(term: ParsedTerm, description: str) -> int | None:
    """Rank how well a portal's term description matches ``term`` (lower is better, None is no match).

    Compares case-insensitively on whitespace-collapsed, stripped text.

    0: the description equals the label.
    1: the description starts with the label followed by whitespace.
    2: the label appears in the description as a whole-word substring.
    3: the season word and the year both appear as separate whole-word tokens, in either order.
    """
    needle = _normalize(term.label)
    haystack = _normalize(description)
    if haystack == needle:
        return 0
    if haystack.startswith(needle) and len(haystack) > len(needle) and haystack[len(needle)].isspace():
        return 1
    if re.search(rf"\b{re.escape(needle)}\b", haystack):
        return 2
    season_found = re.search(rf"\b{re.escape(term.season)}\b", haystack)
    year_found = re.search(rf"\b{term.year}\b", haystack)
    if season_found and year_found:
        return 3
    return None
