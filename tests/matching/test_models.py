from __future__ import annotations

import pytest

from src.matching.models import CourseAlias


def test_alias_keys_use_code_key():
    alias = CourseAlias(cc_id=78, old_code="MAT-1B", new_code="MATH C2220", source="s", status="verified")
    assert (alias.old_key, alias.new_key) == ("MAT|1B", "MATH|C2220")


@pytest.mark.parametrize("kwargs, message", [
    ({"status": "maybe"}, "status"),
    ({"confidence": 1.5}, "confidence"),
    ({"old_code": " "}, "old_code"),
    ({"source": ""}, "source"),
])
def test_alias_validates(kwargs, message):
    base = {"cc_id": 1, "old_code": "A 1", "new_code": "B 1", "source": "s", "status": "verified"}
    with pytest.raises(ValueError, match=message):
        CourseAlias(**{**base, **kwargs})
