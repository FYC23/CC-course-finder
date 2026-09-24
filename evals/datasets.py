"""Load and validate the JSON-lines eval sets under evals/data/."""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from src.decisions.questions import course_equivalent_state, section_modality_state
from src.schedule.models import MODALITIES

DATA_DIR = Path(__file__).parent / "data"
EQUIVALENCE_FILE = DATA_DIR / "course_equivalent.jsonl"
MODALITY_FILE = DATA_DIR / "section_modality.jsonl"
T = TypeVar("T")

_EQUIVALENCE_TEXT = ("id", "college", "assist_code", "assist_title", "articulates_to",
                     "live_code", "live_title", "live_description", "source")
_MODALITY_KEYS = ("id", "raw_tokens", "locations", "has_timed_meetings", "label", "source")


class DatasetInvalid(ValueError):
    """An eval file is malformed. The message names the file and line."""


@dataclass(frozen=True)
class EquivalenceCase:
    case_id: str
    college: str
    assist_code: str
    assist_title: str
    articulates_to: str
    live_code: str
    live_title: str
    live_description: str
    label: bool
    source: str

    def state(self) -> Mapping[str, object]:
        return course_equivalent_state(
            college=self.college, assist_code=self.assist_code, assist_title=self.assist_title,
            articulates_to=self.articulates_to, live_code=self.live_code, live_title=self.live_title,
            live_description=self.live_description,
        )


@dataclass(frozen=True)
class ModalityCase:
    case_id: str
    raw_tokens: tuple[str, ...]
    locations: tuple[str, ...]
    has_timed_meetings: bool
    label: str
    source: str

    def state(self) -> Mapping[str, object]:
        return section_modality_state(
            raw_tokens=self.raw_tokens, locations=self.locations, has_timed_meetings=self.has_timed_meetings
        )


def _load(path: Path, build: Callable[[str, dict[str, Any]], T]) -> tuple[T, ...]:
    cases: list[T] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{path.name} line {number}"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as err:
            raise DatasetInvalid(f"{where}: not JSON: {err.msg}") from err
        if not isinstance(raw, dict):
            raise DatasetInvalid(f"{where}: not a JSON object")
        case = build(where, raw)
        case_id = getattr(case, "case_id")
        if case_id in seen:
            raise DatasetInvalid(f"{where}: duplicate id {case_id!r}")
        seen.add(case_id)
        cases.append(case)
    return tuple(cases)


def _require(where: str, raw: dict[str, Any], keys: tuple[str, ...]) -> None:
    missing = [key for key in keys if key not in raw]
    if missing:
        raise DatasetInvalid(f"{where}: missing {', '.join(missing)}")


def _equivalence(where: str, raw: dict[str, Any]) -> EquivalenceCase:
    _require(where, raw, (*_EQUIVALENCE_TEXT, "label"))
    if not all(isinstance(raw[key], str) for key in _EQUIVALENCE_TEXT):
        raise DatasetInvalid(f"{where}: text fields must be strings")
    if not isinstance(raw["label"], bool):
        raise DatasetInvalid(f"{where}: label must be true or false")
    return EquivalenceCase(case_id=raw["id"], **{k: raw[k] for k in _EQUIVALENCE_TEXT if k != "id"}, label=raw["label"])


def _modality(where: str, raw: dict[str, Any]) -> ModalityCase:
    _require(where, raw, _MODALITY_KEYS)
    if raw["label"] not in MODALITIES:
        raise DatasetInvalid(f"{where}: label must be one of {MODALITIES}, got {raw['label']!r}")
    if not isinstance(raw["has_timed_meetings"], bool):
        raise DatasetInvalid(f"{where}: has_timed_meetings must be true or false")
    return ModalityCase(
        case_id=str(raw["id"]), raw_tokens=tuple(str(t) for t in raw["raw_tokens"]),
        locations=tuple(str(x) for x in raw["locations"]), has_timed_meetings=raw["has_timed_meetings"],
        label=raw["label"], source=str(raw["source"]),
    )


def load_equivalence(path: Path = EQUIVALENCE_FILE) -> tuple[EquivalenceCase, ...]:
    return _load(path, _equivalence)


def load_modality(path: Path = MODALITY_FILE) -> tuple[ModalityCase, ...]:
    return _load(path, _modality)
