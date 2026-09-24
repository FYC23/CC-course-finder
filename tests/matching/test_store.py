from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.matching.models import CourseAlias
from src.matching.store import (
    ensure_alias_table, get_alias, list_aliases, review_alias, upsert_alias,
)


def _alias(status="review", confidence=0.7, new="MATH-C2220", **kwargs):
    return CourseAlias(cc_id=78, old_code="MAT 1B", new_code=new, source="decision:llm",
                       status=status, confidence=confidence, evidence="e", **kwargs)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "assist.sqlite3"
    ensure_alias_table(path)
    return path


def test_insert_then_list(db):
    assert upsert_alias(db, _alias()) == "inserted"
    (stored,) = list_aliases(db)
    assert (stored.old_code, stored.new_code, stored.status, stored.confidence, stored.reviewed) == (
        "MAT 1B", "MATH-C2220", "review", 0.7, False,
    )
    assert stored.alias_id is not None


def test_same_pair_with_other_spelling_is_one_row(db):
    upsert_alias(db, _alias())
    assert upsert_alias(db, _alias(new="MATH C2220", status="accepted", confidence=0.95)) == "updated"
    (stored,) = list_aliases(db)
    assert (stored.new_code, stored.status) == ("MATH C2220", "accepted")


def test_lower_status_does_not_downgrade(db):
    upsert_alias(db, _alias(status="accepted", confidence=0.95))
    assert upsert_alias(db, _alias(status="review", confidence=0.6)) == "kept"
    assert list_aliases(db)[0].status == "accepted"


def test_reviewed_row_is_kept_against_automation(db):
    upsert_alias(db, _alias())
    (row,) = list_aliases(db)
    review_alias(db, row.alias_id, approve=False)
    assert upsert_alias(db, _alias(status="accepted", confidence=0.99)) == "kept"
    assert list_aliases(db)[0].status == "rejected"


def test_manual_alias_always_overwrites(db):
    upsert_alias(db, _alias(status="rejected", confidence=0.1))
    manual = _alias(status="verified", confidence=1.0, reviewed=True)
    assert upsert_alias(db, manual) == "updated"
    stored = list_aliases(db)[0]
    assert (stored.status, stored.reviewed) == ("verified", True)


def test_review_approve_and_get(db):
    upsert_alias(db, _alias())
    alias_id = list_aliases(db)[0].alias_id
    approved = review_alias(db, alias_id, approve=True)
    assert (approved.status, approved.reviewed) == ("verified", True)
    assert get_alias(db, alias_id) == approved


def test_review_unknown_id_raises(db):
    with pytest.raises(KeyError, match="999"):
        review_alias(db, 999, approve=True)


def test_list_filters(db):
    upsert_alias(db, _alias(status="review"))
    upsert_alias(db, CourseAlias(cc_id=35, old_code="MATH 5A", new_code="MATH C2210",
                                 source="catalog_formerly", status="verified"))
    assert [a.cc_id for a in list_aliases(db, cc_id=35)] == [35]
    assert [a.status for a in list_aliases(db, statuses=("review",))] == ["review"]


def test_missing_database_or_table_lists_nothing(tmp_path):
    missing = tmp_path / "none.sqlite3"
    assert list_aliases(missing) == ()
    assert not missing.exists()
    bare = tmp_path / "bare.sqlite3"
    sqlite3.connect(bare).close()
    assert list_aliases(bare) == ()
