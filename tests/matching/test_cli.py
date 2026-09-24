from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import requests
from typer.testing import CliRunner

from src.assist.models import ArticulationRow, IngestRun
from src.assist.store import ensure_db, save_rows, save_run
from src.matching import cli as matching_cli
from src.matching.models import CourseAlias
from src.matching.store import list_aliases, upsert_alias
from src.schedule.colleague_listing import parse_catalog_listing

runner = CliRunner()
_FIXTURES = Path(__file__).parents[1] / "fixtures"
SCHOOL, MAJOR = "University of California, Los Angeles", "Computer Science"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "assist.sqlite3"
    ensure_db(path)
    return path


def _invoke(*args):
    return runner.invoke(matching_cli.app, [str(a) for a in args])


def _pending(db: Path) -> int:
    upsert_alias(db, CourseAlias(78, "MAT 1B", "MATH-C2210", "decision:llm", "review", 0.62, "e"))
    return list_aliases(db)[0].alias_id


def test_review_lists_pending_with_how_to_act(db):
    alias_id = _pending(db)
    result = _invoke("review", "--db", db)
    assert result.exit_code == 0
    assert f"#{alias_id} [review] cc=78 MAT 1B -> MATH-C2210 (decision:llm, p=0.62) e" in result.stdout
    assert "matching approve" in result.stdout


def test_review_empty(db):
    assert "No aliases waiting for review." in _invoke("review", "--db", db).stdout


def test_approve_and_reject(db):
    alias_id = _pending(db)
    assert _invoke("approve", alias_id, "--db", db).exit_code == 0
    assert list_aliases(db)[0].status == "verified"
    assert _invoke("reject", alias_id, "--db", db).exit_code == 0
    assert list_aliases(db)[0].status == "rejected"


def test_approve_unknown_id_exits_1(db):
    result = _invoke("approve", 999, "--db", db)
    assert result.exit_code == 1 and "no alias with id 999" in result.output


def test_add_manual_alias(db):
    result = _invoke("add", "--cc-id", 35, "--old", "MATH 7", "--new", "MATH 17", "--evidence", "catalog 2026", "--db", db)
    assert result.exit_code == 0
    (alias,) = list_aliases(db)
    assert (alias.source, alias.status, alias.reviewed) == ("manual", "verified", True)


def test_add_rejects_unknown_college_and_bad_code(db):
    assert _invoke("add", "--cc-id", 99999, "--old", "A 1", "--new", "B 1", "--evidence", "e", "--db", db).exit_code == 2
    assert _invoke("add", "--cc-id", 35, "--old", "MATH", "--new", "B 1", "--evidence", "e", "--db", db).exit_code == 2


def test_list_filters_by_status(db):
    _pending(db)
    upsert_alias(db, CourseAlias(35, "MATH 5A", "MATH C2210", "catalog_formerly", "verified"))
    result = _invoke("list", "--status", "verified", "--db", db)
    assert "MATH 5A -> MATH C2210" in result.stdout and "MAT 1B" not in result.stdout


def _seed_assist(db: Path) -> None:
    run = IngestRun.create(target_school=SCHOOL, target_major=MAJOR, agreements_seen=1, rows_written=2)
    save_run(db, run)
    save_rows(db, run.run_id, [
        ArticulationRow(target_school=SCHOOL, target_major=MAJOR, target_requirement=uc, uc_equivalent=uc,
                        cc_name="Fresno City College", cc_id=35, course_code=code, course_title=title,
                        agreement_id="1", academic_year="2022-2023", source_url="/a/1")
        for code, title, uc in [("MATH 5A", "Mathematical Analysis I", "MATH 31A"),
                                ("MATH 6", "Mathematical Analysis III", "MATH 32A")]
    ])


class _Lister:
    def __init__(self):
        self.catalog = parse_catalog_listing(json.loads((_FIXTURES / "colleague" / "fcc_math_catalog.json").read_text()))

    def list_subject(self, *, source, term, subject):
        return self.catalog if subject == "MATH" else ()


def test_discover_stores_formerly_alias_then_second_run_is_matched(db, monkeypatch):
    _seed_assist(db)
    monkeypatch.setattr(matching_cli, "build_composite_provider", _Lister)
    monkeypatch.setattr(matching_cli, "decision_provider_from_env", lambda: None)
    first = _invoke("discover", "--cc-id", 35, "--term", "Fall 2026", "--db", db)
    assert first.exit_code == 0, first.output
    assert "MATH 5A: formerly" in first.stdout and "inserted: MATH 5A -> MATH C2210" in first.stdout
    assert "MATH 6: matched (listed as MATH 6)" in first.stdout
    second = _invoke("discover", "--cc-id", 35, "--term", "Fall 2026", "--db", db)
    assert "MATH 5A: matched" in second.stdout


def test_discover_without_assist_rows_exits_1(db):
    result = _invoke("discover", "--cc-id", 35, "--term", "Fall 2026", "--db", db)
    assert result.exit_code == 1 and "No ASSIST rows" in result.output


def test_discover_misconfigured_backend_exits_2(db, monkeypatch):
    _seed_assist(db)

    def broken():
        raise ValueError("DECISION_PROVIDER must be jev, llm, or none; got 'x'")

    monkeypatch.setattr(matching_cli, "decision_provider_from_env", broken)
    result = _invoke("discover", "--cc-id", 35, "--term", "Fall 2026", "--db", db)
    assert result.exit_code == 2 and "DECISION_PROVIDER" in result.output


class _BrokenLister:
    def list_subject(self, *, source, term, subject):
        raise requests.ConnectionError("connection refused")


def test_discover_lister_network_error_exits_1(db, monkeypatch):
    _seed_assist(db)
    monkeypatch.setattr(matching_cli, "build_composite_provider", _BrokenLister)
    monkeypatch.setattr(matching_cli, "decision_provider_from_env", lambda: None)
    result = _invoke("discover", "--cc-id", 35, "--term", "Fall 2026", "--db", db)
    assert result.exit_code == 1
    assert "Fresno City College" in result.output
    assert "ConnectionError" in result.output and "connection refused" in result.output


def test_export_appends_new_verified_rows_once(db, tmp_path):
    seed = tmp_path / "course_aliases.csv"
    seed.write_text("cc_ids,old_code,new_code,source,evidence\n78,MAT-1B,MATH-C2220,rccd_crosswalk,page\n")
    upsert_alias(db, CourseAlias(78, "MAT 1B", "MATH C2220", "manual", "verified", reviewed=True))
    upsert_alias(db, CourseAlias(35, "MATH 5A", "MATH C2210", "catalog_formerly", "verified", evidence="note"))
    upsert_alias(db, CourseAlias(35, "MATH 5B", "MATH 6", "decision:llm", "review", 0.6))
    assert _invoke("export", "--db", db, "--out", seed).exit_code == 0
    assert _invoke("export", "--db", db, "--out", seed).exit_code == 0
    rows = list(csv.reader(seed.open()))
    assert rows[1:] == [
        ["78", "MAT-1B", "MATH-C2220", "rccd_crosswalk", "page"],
        ["35", "MATH 5A", "MATH C2210", "catalog_formerly", "note"],
    ]


def test_import_rccd_prints_seed_rows():
    result = _invoke("import-rccd", "--html", _FIXTURES / "matching" / "rccd_ccn_excerpt.html", "--checked-on", "2026-09-23")
    assert result.exit_code == 0
    assert "78 148 149,MAT-1B,MATH-C2220,rccd_crosswalk" in result.stdout
