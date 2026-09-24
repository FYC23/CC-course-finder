"""Shared text-extraction helpers for JSON values and HTML elements.

Used by both ``captures.py`` and ``extractor.py`` so the rules for turning a raw JSON
value or a bs4 element into a plain string live in exactly one place.
"""
from __future__ import annotations

from typing import Any

from bs4.element import Tag


def stringify(value: Any) -> str:
    if value is None or value is False:
        return ""
    if value is True:
        return "true"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def element_text(element: Tag, attr: str | None = None) -> str:
    if attr:
        value = element.get(attr)
        if value is None:
            return ""
        if isinstance(value, list):
            return " ".join(value).strip()
        return str(value).strip()
    return " ".join(element.get_text(" ").split())
