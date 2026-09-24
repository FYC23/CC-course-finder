"""A deliberately small JSONPath subset for replay specs.

Supported: ``$``, ``.name``, ``["quoted name"]`` / ``['quoted name']``, ``[N]`` (an
integer index, negative allowed) and ``[*]`` (every element of a list, or every value of
an object). Nothing else: no filters, recursion, slices or unions. Specs are recorded
data, and a tiny path language keeps extraction deterministic and easy to test.
"""
from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(
    r"""\.([A-Za-z0-9_\-]+)            # .name
      | \[\*\]                          # [*]
      | \[(-?\d+)\]                     # [N]
      | \[(?:"([^"]*)"|'([^']*)')\]     # ["name"] or ['name']
    """,
    re.VERBOSE,
)


class JsonPathError(ValueError):
    """The path uses syntax outside the supported subset."""


class _Wildcard:
    def __repr__(self) -> str:
        return "[*]"


WILDCARD = _Wildcard()


def parse_path(path: str) -> tuple[object, ...]:
    """Split ``$.a[*].b`` into ``('a', WILDCARD, 'b')``. Raises JsonPathError otherwise."""
    if not path.startswith("$"):
        raise JsonPathError(f"JSONPath must start with '$': {path!r}")
    tokens: list[object] = []
    pos = 1
    while pos < len(path):
        match = _TOKEN_RE.match(path, pos)
        if match is None:
            raise JsonPathError(f"Unsupported JSONPath syntax at offset {pos} in {path!r}")
        tokens.append(_token_of(match))
        pos = match.end()
    return tuple(tokens)


def _token_of(match: re.Match[str]) -> object:
    name, index, dq_name, sq_name = match.groups()
    if name is not None:
        return name
    if index is not None:
        return int(index)
    if dq_name is not None:
        return dq_name
    if sq_name is not None:
        return sq_name
    return WILDCARD


def resolve(doc: Any, path: str) -> list[Any]:
    """Every value the path selects, in document order. Missing keys select nothing;
    a key whose value is ``null`` selects ``None``."""
    current: list[Any] = [doc]
    for token in parse_path(path):
        current = [child for node in current for child in _step(node, token)]
    return current


def first(doc: Any, path: str) -> Any | None:
    matches = resolve(doc, path)
    return matches[0] if matches else None


def _step(node: Any, token: object) -> list[Any]:
    if token is WILDCARD:
        if isinstance(node, list):
            return list(node)
        if isinstance(node, dict):
            return list(node.values())
        return []
    if isinstance(token, int):
        if isinstance(node, list) and -len(node) <= token < len(node):
            return [node[token]]
        return []
    if isinstance(node, dict) and token in node:
        return [node[token]]
    return []
