"""Loads every replay spec under ``src/schedule/data/specs`` once and serves them by cc_id.

Loading fails fast: one invalid file raises ``SpecInvalid`` naming it, so a bad spec is
caught by the test suite (tests/schedule/replay/test_specs_registry.py) rather than at
query time.
"""
from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from ..errors import SpecInvalid
from .spec import ReplaySpec, load_spec

SPECS_DIR = Path(__file__).parent.parent / "data" / "specs"


def load_specs_from(directory: Path) -> Mapping[int, ReplaySpec]:
    """Every ``<cc_id>.json`` in ``directory``, keyed by cc_id. Empty when none exist."""
    specs: dict[int, ReplaySpec] = {}
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        spec = load_spec(path)
        if path.stem != str(spec.cc_id):
            raise SpecInvalid(f"{path}: file name must be <cc_id>.json, got cc_id={spec.cc_id}")
        if spec.cc_id in specs:
            raise SpecInvalid(f"{path}: duplicate cc_id {spec.cc_id}")
        specs[spec.cc_id] = spec
    return MappingProxyType(specs)


@lru_cache(maxsize=1)
def load_all_specs() -> Mapping[int, ReplaySpec]:
    return load_specs_from(SPECS_DIR)
