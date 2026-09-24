"""Decision state is data built from frozen objects; backends need plain JSON values."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def to_plain(value: Any) -> Any:
    """MappingProxyType and other mappings become dicts, tuples become lists, recursively."""
    if isinstance(value, Mapping):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(item) for item in value]
    return value
