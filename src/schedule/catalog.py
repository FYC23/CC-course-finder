from __future__ import annotations

import json
from pathlib import Path

from .models import CollegeScheduleSource

_DATA_FILE = Path(__file__).parent / "data" / "colleges.json"
_KNOWN_SYSTEMS = {"banner", "wvm_static", "banner_ssb_classic", "vsb_4cd"}


def _validate_entry(e: dict) -> None:
    for key in ("cc_id", "cc_name", "system", "base_url", "locations"):
        if key not in e:
            raise ValueError(f"colleges.json entry missing key {key!r}: {e}")
    if e["system"] not in _KNOWN_SYSTEMS:
        raise ValueError(f"Unknown system {e['system']!r} in entry cc_id={e['cc_id']}")
    if not e["locations"]:
        raise ValueError(f"Empty locations for cc_id={e['cc_id']}")
    if "source_url" in e and not isinstance(e["source_url"], str):
        raise ValueError(f"source_url must be string for cc_id={e['cc_id']}")


def _load(path: Path | None = None) -> dict[int, CollegeScheduleSource]:
    target = path or _DATA_FILE
    try:
        data = json.loads(target.read_text())
    except FileNotFoundError as exc:
        raise RuntimeError(f"colleges.json missing: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"colleges.json corrupt: {exc}") from exc
    for e in data:
        _validate_entry(e)
    return {
        e["cc_id"]: CollegeScheduleSource(
            cc_id=e["cc_id"],
            cc_name=e["cc_name"],
            system=e["system"],
            base_url=e["base_url"],
            locations=tuple(e["locations"]),
        )
        for e in data
    }


_SOURCES_BY_CC_ID: dict[int, CollegeScheduleSource] = _load()


def _reload(path: Path | None = None) -> None:
    """Reload catalog from *path* (or default data file). Intended for tests."""
    global _SOURCES_BY_CC_ID
    _SOURCES_BY_CC_ID = _load(path)


def get_college_source(cc_id: int) -> CollegeScheduleSource:
    source = _SOURCES_BY_CC_ID.get(cc_id)
    if source is None:
        raise KeyError(f"No schedule source configured for cc_id={cc_id}")
    return source


def find_college_source_by_name(name: str) -> CollegeScheduleSource:
    """Case-insensitive substring match. Raises KeyError if 0 or >1 matches."""
    needle = name.strip().lower()
    matches = [
        s for s in _SOURCES_BY_CC_ID.values()
        if needle in s.cc_name.lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) == 0:
        raise KeyError(f"No schedule source matches name={name!r}")
    names = ", ".join(f"{s.cc_name!r} (cc_id={s.cc_id})" for s in matches)
    raise KeyError(f"Ambiguous name {name!r} matches: {names}")
