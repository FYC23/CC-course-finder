"""Parse the RCCD common course numbering page into seed rows.

    https://www.rccd.edu/commoncoursenumbering/index.html

The site's TLS chain is incomplete for Python's certificate store, so a maintainer saves
the page from a browser and runs `matching import-rccd --html FILE`, then reviews the diff
of src/matching/data/course_aliases.csv. One district crosswalk covers all three colleges.
"""
from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from dataclasses import dataclass

from bs4 import BeautifulSoup

RCCD_CC_IDS: tuple[int, ...] = (78, 148, 149)
SOURCE = "rccd_crosswalk"
_CELL_RE = re.compile(r"^(?P<code>[A-Z]{2,5}-[A-Z]?\d{1,4}[A-Z]{0,2})\s+(?P<title>.+)$")


@dataclass(frozen=True)
class CrosswalkRow:
    old_code: str
    old_title: str
    new_code: str
    new_title: str
    section: str


def parse_rccd_crosswalk(html: str) -> tuple[CrosswalkRow, ...]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[CrosswalkRow] = []
    for table in soup.find_all("table"):
        heading = table.find_previous(["h2", "h3"])
        section = heading.get_text(" ", strip=True) if heading else ""
        for tr in table.select("tbody tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(cells) != 2:
                continue
            old, new = _CELL_RE.match(cells[0]), _CELL_RE.match(cells[1])
            if old and new:
                rows.append(CrosswalkRow(old["code"], old["title"], new["code"], new["title"], section))
    if not rows:
        raise ValueError("no crosswalk rows found; the RCCD page layout may have changed")
    return tuple(rows)


def seed_csv(rows: Iterable[CrosswalkRow], *, checked_on: str) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["cc_ids", "old_code", "new_code", "source", "evidence"])
    cc_ids = " ".join(str(cc_id) for cc_id in RCCD_CC_IDS)
    for row in rows:
        evidence = f"rccd.edu/commoncoursenumbering: {row.section}; checked {checked_on}"
        writer.writerow([cc_ids, row.old_code, row.new_code, SOURCE, evidence])
    return buffer.getvalue()
