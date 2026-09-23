from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

from .models import CATALOG_STATUSES, CollegeScheduleSource

_DATA_FILE = Path(__file__).parent / "data" / "colleges.json"

KNOWN_SYSTEMS: frozenset[str] = frozenset(
    {
        "colleague_selfservice",
        "banner9_ssb",
        "wvm_static",
        "vsb_4cd",
        "marin_colleague",
        "smcccd_colleague",
    }
)
# Legacy names still accepted on disk and mapped to their real family.
SYSTEM_ALIASES: dict[str, str] = {
    "banner": "colleague_selfservice",
    "banner_ssb_classic": "banner9_ssb",
}
_REQUIRED_KEYS = ("cc_id", "cc_name", "system", "base_url", "locations")


def _canonical_system(name: str) -> str:
    return SYSTEM_ALIASES.get(name, name)


def _validate_entry(e: dict) -> None:
    for key in _REQUIRED_KEYS:
        if key not in e:
            raise ValueError(f"colleges.json entry missing key {key!r}: {e}")
    if _canonical_system(e["system"]) not in KNOWN_SYSTEMS:
        raise ValueError(f"Unknown system {e['system']!r} in entry cc_id={e['cc_id']}")
    if not isinstance(e["locations"], list):
        raise ValueError(f"locations must be a list for cc_id={e['cc_id']}")
    if "source_url" in e and not isinstance(e["source_url"], str):
        raise ValueError(f"source_url must be string for cc_id={e['cc_id']}")
    _validate_params(e)
    _validate_status(e)


def _validate_params(e: dict) -> None:
    params = e.get("params", {})
    if not isinstance(params, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in params.items()
    ):
        raise ValueError(f"params must be a string-to-string object for cc_id={e['cc_id']}")


def _validate_status(e: dict) -> None:
    status = e.get("status", "active")
    if status not in CATALOG_STATUSES:
        raise ValueError(
            f"status must be one of {CATALOG_STATUSES} for cc_id={e['cc_id']}, got {status!r}"
        )


def _to_source(e: dict) -> CollegeScheduleSource:
    return CollegeScheduleSource(
        cc_id=e["cc_id"],
        cc_name=e["cc_name"],
        system=_canonical_system(e["system"]),
        base_url=e["base_url"],
        locations=tuple(e["locations"]),
        params=MappingProxyType(dict(e.get("params", {}))),
        status=e.get("status", "active"),
    )


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
    return {e["cc_id"]: _to_source(e) for e in data}


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


def list_college_sources() -> list[CollegeScheduleSource]:
    return list(_SOURCES_BY_CC_ID.values())


def find_college_source_by_name(name: str) -> CollegeScheduleSource:
    """Case-insensitive substring match. Raises KeyError if 0 or >1 matches."""
    needle = name.strip().lower()
    matches = [s for s in _SOURCES_BY_CC_ID.values() if needle in s.cc_name.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) == 0:
        raise KeyError(f"No schedule source matches name={name!r}")
    names = ", ".join(f"{s.cc_name!r} (cc_id={s.cc_id})" for s in matches)
    raise KeyError(f"Ambiguous name {name!r} matches: {names}")
