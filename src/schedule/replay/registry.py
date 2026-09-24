"""Loads every replay spec under ``src/schedule/data/specs`` once and serves them by cc_id.

Two modes. Strict (the default for ``load_specs_from``) raises ``SpecInvalid`` on the first
invalid file, file-name mismatch, or duplicate cc_id; the test suite
(tests/schedule/replay/test_specs_registry.py) and ``cli validate`` use it so a bad spec
fails fast. At runtime ``load_all_specs`` loads non-strictly: an invalid spec is logged
(naming the file and field) and skipped, so only that college shows "Couldn't check"
instead of every search failing.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from ..errors import SpecInvalid
from .spec import ReplaySpec, load_spec

logger = logging.getLogger(__name__)

SPECS_DIR = Path(__file__).parent.parent / "data" / "specs"


def load_specs_from(directory: Path, *, strict: bool = True) -> Mapping[int, ReplaySpec]:
    """Every ``<cc_id>.json`` in ``directory``, keyed by cc_id. Empty when none exist.

    ``strict`` raises on the first problem; otherwise each bad file is logged and skipped.
    """
    specs: dict[int, ReplaySpec] = {}
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            spec = _load_checked(path, specs)
        except SpecInvalid as err:
            if strict:
                raise
            logger.error("Skipping replay spec %s: %s", path.name, err)
            continue
        specs[spec.cc_id] = spec
    return MappingProxyType(specs)


def _load_checked(path: Path, loaded: Mapping[int, ReplaySpec]) -> ReplaySpec:
    spec = load_spec(path)
    if path.stem != str(spec.cc_id):
        raise SpecInvalid(f"{path}: file name must be <cc_id>.json, got cc_id={spec.cc_id}")
    if spec.cc_id in loaded:
        raise SpecInvalid(f"{path}: duplicate cc_id {spec.cc_id}")
    return spec


@lru_cache(maxsize=1)
def load_all_specs() -> Mapping[int, ReplaySpec]:
    """The runtime spec set: invalid files are logged and skipped, not raised."""
    return load_specs_from(SPECS_DIR, strict=False)
