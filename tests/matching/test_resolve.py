from __future__ import annotations

from pathlib import Path

import pytest

from src.matching import resolve
from src.matching.models import CourseAlias, SubjectRename
from src.matching.resolve import CourseResolver, LiveCode, load_resolver
from src.matching.seeds import SeedInvalid
from src.matching.store import ensure_alias_table, list_aliases, review_alias, upsert_alias

_SEED = (
    CourseAlias(cc_id=78, old_code="MAT-1B", new_code="MATH-C2220", source="rccd_crosswalk", status="verified"),
    CourseAlias(cc_id=78, old_code="ENGL-1B", new_code="ENGL-C1003", source="rccd_crosswalk", status="verified"),
)
_RENAMES = (
    SubjectRename(cc_id=78, old_subject="MAT", new_subject="MATH", source="rccd_live_listing"),
    SubjectRename(cc_id=78, old_subject="ENG", new_subject="ENGL", source="rccd_crosswalk"),
)


def _codes(resolver, cc_id, code):
    return [(c.code, c.source, c.status) for c in resolver.live_codes(cc_id, code)]


def test_alias_then_renamed_spelling_then_assist_code():
    resolver = CourseResolver(aliases=_SEED, renames=_RENAMES)
    assert _codes(resolver, 78, "MAT 1B") == [
        ("MATH-C2220", "rccd_crosswalk", "verified"),
        ("MATH 1B", "rccd_live_listing", "verified"),
        ("MAT 1B", "", ""),
    ]


def test_rename_chains_into_an_alias():
    resolver = CourseResolver(aliases=_SEED, renames=_RENAMES)
    assert [c.code for c in resolver.live_codes(78, "ENG 1B")] == ["ENGL-C1003", "ENGL 1B", "ENG 1B"]


def test_rename_only():
    resolver = CourseResolver(aliases=_SEED, renames=_RENAMES)
    assert [c.code for c in resolver.live_codes(78, "MAT 1C")] == ["MATH 1C", "MAT 1C"]


def test_other_college_is_untouched():
    resolver = CourseResolver(aliases=_SEED, renames=_RENAMES)
    assert resolver.live_codes(2, "MAT 1B") == (LiveCode("MAT 1B"),)
    assert not resolver.live_codes(2, "MAT 1B")[0].is_alias


def test_verified_before_accepted_and_review_ignored():
    aliases = (
        CourseAlias(cc_id=5, old_code="A 1", new_code="B 1", source="decision:llm", status="accepted", confidence=0.99),
        CourseAlias(cc_id=5, old_code="A 1", new_code="C 1", source="manual", status="verified"),
        CourseAlias(cc_id=5, old_code="A 1", new_code="D 1", source="decision:llm", status="review", confidence=0.8),
    )
    assert [c.code for c in CourseResolver(aliases=aliases).live_codes(5, "A 1")] == ["C 1", "B 1", "A 1"]


def test_blocked_pairs_are_dropped():
    blocked = (CourseAlias(cc_id=78, old_code="MAT 1B", new_code="MATH C2220", source="manual", status="rejected"),)
    resolver = CourseResolver(aliases=_SEED, renames=_RENAMES, blocked=blocked)
    assert [c.code for c in resolver.live_codes(78, "MAT 1B")] == ["MATH 1B", "MAT 1B"]


def test_duplicates_by_key_are_dropped_and_list_is_capped():
    """Non-ASSIST candidates are capped at MAX_LOOKUPS_PER_COURSE - 1 so the last slot is
    always reserved for the ASSIST code itself, which must never be crowded out."""
    aliases = tuple(
        CourseAlias(cc_id=5, old_code="A 1", new_code=new, source="s", status="verified")
        for new in ("B 1", "B-1", "C 1", "D 1")
    )
    codes = CourseResolver(aliases=aliases).live_codes(5, "A 1")
    assert [c.code for c in codes] == ["B 1", "C 1", "A 1"]
    assert len(codes) == resolve.MAX_LOOKUPS_PER_COURSE


def test_has_alias_ignores_bare_renames():
    resolver = CourseResolver(aliases=_SEED, renames=_RENAMES)
    assert resolver.has_alias(78, "MAT 1B") and resolver.has_alias(78, "ENG 1B")
    assert not resolver.has_alias(78, "MAT 1C")


def test_renamed_subjects():
    resolver = CourseResolver(renames=_RENAMES)
    assert resolver.renamed_subjects(78, "mat") == ("MATH",)
    assert resolver.renamed_subjects(2, "MAT") == ()


def test_load_resolver_uses_committed_seeds_without_a_database(tmp_path: Path):
    resolver = load_resolver(tmp_path / "missing.sqlite3")
    assert [c.code for c in resolver.live_codes(78, "MAT 1B")] == ["MATH-C2220", "MATH 1B", "MAT 1B"]


def test_load_resolver_adds_accepted_and_honors_human_rejections(tmp_path: Path):
    db = tmp_path / "assist.sqlite3"
    ensure_alias_table(db)
    upsert_alias(db, CourseAlias(cc_id=35, old_code="MATH 5A", new_code="MATH C2210",
                                 source="decision:llm", status="accepted", confidence=0.95))
    upsert_alias(db, CourseAlias(cc_id=78, old_code="MAT 1B", new_code="MATH-C2220",
                                 source="decision:llm", status="review", confidence=0.6))
    alias_id = list_aliases(db, cc_id=78)[0].alias_id
    review_alias(db, alias_id, approve=False)
    resolver = load_resolver(db)
    assert [c.code for c in resolver.live_codes(35, "MATH 5A")] == ["MATH C2210", "MATH 5A"]
    assert [c.code for c in resolver.live_codes(78, "MAT 1B")] == ["MATH 1B", "MAT 1B"]


def test_unreviewed_rejection_does_not_block_a_seed(tmp_path: Path):
    db = tmp_path / "assist.sqlite3"
    upsert_alias(db, CourseAlias(cc_id=78, old_code="MAT 1B", new_code="MATH-C2220",
                                 source="decision:llm", status="rejected", confidence=0.1))
    assert load_resolver(db).live_codes(78, "MAT 1B")[0].code == "MATH-C2220"


def test_invalid_seed_files_fall_back_to_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog):
    def broken():
        raise SeedInvalid("course_aliases.csv:2: bad")

    monkeypatch.setattr(resolve, "load_seed_aliases", broken)
    resolver = load_resolver(tmp_path / "missing.sqlite3")
    assert resolver.live_codes(78, "MAT 1B") == (LiveCode("MAT 1B"),)
    assert "seed files are invalid" in caplog.text
