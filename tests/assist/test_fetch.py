from __future__ import annotations

from pathlib import Path

from src.assist.fetch import ArtifactFetcher
from src.assist.models import AgreementRef


class _DummyClient:
    def __init__(self) -> None:
        self.last_path: str | None = None
        self.last_accept_pdf = False

    def get_bytes(self, path: str, accept_pdf: bool = False) -> bytes:
        self.last_path = path
        self.last_accept_pdf = accept_pdf
        return b"%PDF-1.4"


def test_artifact_path_sanitizes_slash_key(tmp_path: Path) -> None:
    fetcher = ArtifactFetcher(client=_DummyClient(), artifact_dir=tmp_path)
    ref = AgreementRef(
        target_school_id=117,
        target_school_name="University of California, Los Angeles",
        target_major="Computer Science",
        cc_id=54,
        cc_name="De Anza College",
        academic_year_id=76,
        academic_year_label="2025-2026",
        agreement_id="76/54/to/117/Major/abc",
        artifact_url="/api/artifacts/76/54/to/117/Major/abc",
    )
    path = fetcher.artifact_path(ref)
    assert "/" not in path.name
    assert path.name.endswith(".pdf")


def test_fetch_artifact_encodes_non_numeric_key_path(tmp_path: Path) -> None:
    client = _DummyClient()
    fetcher = ArtifactFetcher(client=client, artifact_dir=tmp_path)
    ref = AgreementRef(
        target_school_id=117,
        target_school_name="University of California, Los Angeles",
        target_major="Computer Science",
        cc_id=54,
        cc_name="De Anza College",
        academic_year_id=76,
        academic_year_label="2025-2026",
        agreement_id="76/54/to/117/Major/abc 123",
        artifact_url="/api/artifacts/76/54/to/117/Major/abc 123",
    )
    fetcher.fetch_artifact(ref, force=True)
    assert client.last_accept_pdf is True
    assert client.last_path == "/api/artifacts/76/54/to/117/Major/abc%20123"


def test_fetch_artifact_with_status_reports_cache_hit(tmp_path: Path) -> None:
    client = _DummyClient()
    fetcher = ArtifactFetcher(client=client, artifact_dir=tmp_path)
    ref = AgreementRef(
        target_school_id=117,
        target_school_name="University of California, Los Angeles",
        target_major="Computer Science",
        cc_id=54,
        cc_name="De Anza College",
        academic_year_id=76,
        academic_year_label="2025-2026",
        agreement_id="26089328",
        artifact_url="/api/artifacts/26089328",
    )
    first_path, first_downloaded = fetcher.fetch_artifact_with_status(ref)
    second_path, second_downloaded = fetcher.fetch_artifact_with_status(ref)

    assert first_path == second_path
    assert first_downloaded is True
    assert second_downloaded is False

