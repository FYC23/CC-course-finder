from __future__ import annotations

from pathlib import Path

import requests

from src.assist.models import AgreementRef, ArticulationRow
from src.assist.pipeline import ingest_target_major
from src.assist.store import ensure_db, query_rows, save_rows


class _FakeDiscovery:
    def __init__(self, refs: list[AgreementRef]) -> None:
        self._refs = refs

    def discover_major_agreements(
        self,
        target_school_name: str,
        major_name: str,
        max_community_colleges: int | None = None,
    ) -> list[AgreementRef]:
        return self._refs[: max_community_colleges or len(self._refs)]


class _FallbackFetcher:
    def __init__(self, artifact_dir: Path) -> None:
        self.artifact_dir = artifact_dir
        self.calls: list[str] = []

    def fetch_artifact(self, ref: AgreementRef, force: bool = False) -> Path:
        self.calls.append(ref.agreement_id)
        if ref.agreement_id == "76/2/to/117/Major/new":
            response = requests.Response()
            response.status_code = 404
            response.url = "https://assist.org/api/artifacts/76/2/to/117/Major/new"
            raise requests.HTTPError("404 not found", response=response)
        out = self.artifact_dir / "report.pdf"
        out.write_bytes(b"%PDF-1.4")
        return out


def test_ingest_falls_back_to_numeric_key_on_404(
    tmp_path: Path, monkeypatch
) -> None:
    ref = AgreementRef(
        target_school_id=117,
        target_school_name="University of California, Los Angeles",
        target_major="Computer Science",
        cc_id=2,
        cc_name="Evergreen Valley College",
        academic_year_id=76,
        academic_year_label="2025-2026",
        agreement_id="76/2/to/117/Major/new",
        artifact_url="/api/artifacts/76/2/to/117/Major/new",
        fallback_academic_year_id=73,
        fallback_academic_year_label="2022-2023",
        fallback_agreement_id="26089328",
        fallback_artifact_url="/api/artifacts/26089328",
    )
    logs: list[str] = []

    def _fake_extract(_: Path) -> str:
        return "stub text"

    def _fake_parse(ref_used: AgreementRef, _: str) -> list[ArticulationRow]:
        return [
            ArticulationRow(
                target_school=ref_used.target_school_name,
                target_major=ref_used.target_major,
                target_requirement="MATH 31B",
                uc_equivalent="MATH 31B",
                cc_name=ref_used.cc_name,
                cc_id=ref_used.cc_id,
                course_code="MATH 1B",
                course_title="Calculus II",
                agreement_id=ref_used.agreement_id,
                academic_year=ref_used.academic_year_label or str(ref_used.academic_year_id),
                source_url=ref_used.artifact_url,
            )
        ]

    monkeypatch.setattr("src.assist.pipeline.extract_text_from_pdf", _fake_extract)
    monkeypatch.setattr("src.assist.pipeline.parse_articulation_rows", _fake_parse)

    fetcher = _FallbackFetcher(artifact_dir=tmp_path)
    run = ingest_target_major(
        discovery=_FakeDiscovery([ref]),
        fetcher=fetcher,
        db_path=tmp_path / "assist.sqlite3",
        target_school=ref.target_school_name,
        major_name=ref.target_major,
        max_community_colleges=1,
        log=logs.append,
    )

    assert fetcher.calls == ["76/2/to/117/Major/new", "26089328"]
    assert run.rows_written == 1
    assert any("falling back" in msg for msg in logs)

    stored = query_rows(
        tmp_path / "assist.sqlite3",
        target_school=ref.target_school_name,
        target_major=ref.target_major,
    )
    assert len(stored) == 1
    assert stored[0].agreement_id == "26089328"


def test_ingest_emits_progress_logs(tmp_path: Path, monkeypatch) -> None:
    ref = AgreementRef(
        target_school_id=117,
        target_school_name="University of California, Los Angeles",
        target_major="Computer Science",
        cc_id=2,
        cc_name="Evergreen Valley College",
        academic_year_id=76,
        academic_year_label="2025-2026",
        agreement_id="26089328",
        artifact_url="/api/artifacts/26089328",
    )
    logs: list[str] = []

    def _fake_extract(_: Path) -> str:
        return "MATH 31B ← MATH 1B"

    def _fake_parse(ref_used: AgreementRef, _: str) -> list[ArticulationRow]:
        return [
            ArticulationRow(
                target_school=ref_used.target_school_name,
                target_major=ref_used.target_major,
                target_requirement="MATH 31B",
                uc_equivalent="MATH 31B",
                cc_name=ref_used.cc_name,
                cc_id=ref_used.cc_id,
                course_code="MATH 1B",
                course_title="Calculus II",
                agreement_id=ref_used.agreement_id,
                academic_year=ref_used.academic_year_label or str(ref_used.academic_year_id),
                source_url=ref_used.artifact_url,
            )
        ]

    monkeypatch.setattr("src.assist.pipeline.extract_text_from_pdf", _fake_extract)
    monkeypatch.setattr("src.assist.pipeline.parse_articulation_rows", _fake_parse)

    fetcher = _FallbackFetcher(artifact_dir=tmp_path)
    run = ingest_target_major(
        discovery=_FakeDiscovery([ref]),
        fetcher=fetcher,
        db_path=tmp_path / "assist.sqlite3",
        target_school=ref.target_school_name,
        major_name=ref.target_major,
        max_community_colleges=1,
        log=logs.append,
    )

    assert run.rows_written == 1
    assert any("Discovering agreements" in msg for msg in logs)
    assert any("Processing Evergreen Valley College" in msg for msg in logs)
    assert any("Parsed 1 articulation rows" in msg for msg in logs)
    assert any("Artifact fetch stats" in msg for msg in logs)
    assert any("Ingest complete" in msg for msg in logs)


def _ref(cc_id: int, agreement_id: str) -> AgreementRef:
    return AgreementRef(
        target_school_id=117,
        target_school_name="University of California, Los Angeles",
        target_major="Computer Science",
        cc_id=cc_id,
        cc_name=f"College {cc_id}",
        academic_year_id=73,
        academic_year_label="2022-2023",
        agreement_id=agreement_id,
        artifact_url=f"/api/artifacts/{agreement_id}",
    )


def _stored_row(ref: AgreementRef, course_code: str) -> ArticulationRow:
    return ArticulationRow(
        target_school=ref.target_school_name,
        target_major=ref.target_major,
        target_requirement="COM SCI 33",
        uc_equivalent="COM SCI 33",
        cc_name=ref.cc_name,
        cc_id=ref.cc_id,
        course_code=course_code,
        course_title="",
        agreement_id=ref.agreement_id,
        academic_year=ref.academic_year_label or "",
        source_url=ref.artifact_url,
    )


def test_reingest_replaces_stale_rows_only_for_colleges_it_parsed(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "assist.sqlite3"
    parsed, unreachable = _ref(2, "26089328"), _ref(3, "404")
    ensure_db(db_path)
    save_rows(
        db_path,
        "old-run",
        [_stored_row(parsed, "MATH 61"), _stored_row(unreachable, "CS 21")],
    )

    class _Fetcher:
        def fetch_artifact(self, ref: AgreementRef, force: bool = False) -> Path:
            if ref.agreement_id == "404":
                response = requests.Response()
                response.status_code = 500
                raise requests.HTTPError("server error", response=response)
            return tmp_path / "report.pdf"

    monkeypatch.setattr("src.assist.pipeline.extract_text_from_pdf", lambda _: "")
    monkeypatch.setattr(
        "src.assist.pipeline.parse_articulation_rows",
        lambda ref_used, _: [_stored_row(ref_used, "CISP 310")],
    )

    ingest_target_major(
        discovery=_FakeDiscovery([parsed, unreachable]),
        fetcher=_Fetcher(),
        db_path=db_path,
        target_school="UCLA",
        major_name="Computer Science",
    )

    stored = query_rows(db_path, parsed.target_school_name, parsed.target_major)
    assert {(row.cc_id, row.course_code) for row in stored} == {(2, "CISP 310"), (3, "CS 21")}


def test_reingest_keeps_rows_of_a_college_that_now_parses_to_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    """An empty parse more likely means ASSIST changed its layout than that every
    articulation vanished, so it must not wipe the college's rows."""
    db_path = tmp_path / "assist.sqlite3"
    ref = _ref(2, "26089328")
    ensure_db(db_path)
    save_rows(db_path, "old-run", [_stored_row(ref, "MATH 070")])

    class _Fetcher:
        def fetch_artifact(self, ref: AgreementRef, force: bool = False) -> Path:
            return tmp_path / "report.pdf"

    logs: list[str] = []
    monkeypatch.setattr("src.assist.pipeline.extract_text_from_pdf", lambda _: "")
    monkeypatch.setattr("src.assist.pipeline.parse_articulation_rows", lambda ref_used, _: [])

    ingest_target_major(
        discovery=_FakeDiscovery([ref]),
        fetcher=_Fetcher(),
        db_path=db_path,
        target_school="UCLA",
        major_name="Computer Science",
        log=logs.append,
    )

    stored = query_rows(db_path, ref.target_school_name, ref.target_major)
    assert [row.course_code for row in stored] == ["MATH 070"]
    assert any("kept" in msg and "College 2" in msg for msg in logs)
