from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

import requests

from .discovery import AssistDiscovery
from .fetch import ArtifactFetcher
from .models import ArticulationRow, IngestRun
from .normalize import dedupe_rows, filter_empty_course_codes
from .parser import extract_text_from_pdf, parse_articulation_rows
from .store import ensure_db, save_rows, save_run


def ingest_target_major(
    discovery: AssistDiscovery,
    fetcher: ArtifactFetcher,
    db_path: Path,
    target_school: str,
    major_name: str,
    max_community_colleges: int | None = None,
    log: Callable[[str], None] | None = None,
) -> IngestRun:
    max_cc_label = (
        str(max_community_colleges)
        if max_community_colleges is not None
        else "all"
    )

    def _emit(message: str) -> None:
        if log:
            log(message)

    _emit(
        "Discovering agreements "
        f"for target='{target_school}' major='{major_name}' "
        f"(max_cc={max_cc_label})."
    )
    refs = discovery.discover_major_agreements(
        target_school_name=target_school,
        major_name=major_name,
        max_community_colleges=max_community_colleges,
    )
    _emit(f"Discovery complete: {len(refs)} agreements to process.")

    all_rows: list[ArticulationRow] = []
    download_count = 0
    cache_hit_count = 0
    total_refs = len(refs)

    def _fetch_with_status(ref: AgreementRef) -> tuple[Path, bool]:
        fetch_with_status = getattr(fetcher, "fetch_artifact_with_status", None)
        if callable(fetch_with_status):
            return fetch_with_status(ref)
        return fetcher.fetch_artifact(ref), True

    for index, ref in enumerate(refs, start=1):
        try:
            _emit(
                f"[{index}/{total_refs}] Processing {ref.cc_name} "
                f"(agreement {ref.agreement_id})."
            )
            parse_ref = ref
            try:
                _emit(
                    f"[{index}/{total_refs}] Fetching artifact for "
                    f"{parse_ref.cc_name} agreement {parse_ref.agreement_id}."
                )
                pdf_path, downloaded = _fetch_with_status(parse_ref)
                if downloaded:
                    download_count += 1
                else:
                    cache_hit_count += 1
            except requests.HTTPError as err:
                status_code = err.response.status_code if err.response is not None else None
                if status_code != 404 or not ref.fallback_agreement_id:
                    _emit(
                        "Artifact fetch failed "
                        f"for {ref.cc_name} agreement {ref.agreement_id} "
                        f"(status={status_code}); skipping."
                    )
                    continue
                parse_ref = replace(
                    ref,
                    academic_year_id=ref.fallback_academic_year_id or ref.academic_year_id,
                    academic_year_label=(
                        ref.fallback_academic_year_label or ref.academic_year_label
                    ),
                    agreement_id=ref.fallback_agreement_id,
                    artifact_url=ref.fallback_artifact_url or ref.artifact_url,
                )
                _emit(
                    "Artifact 404 for newest agreement "
                    f"{ref.agreement_id} ({ref.academic_year_label or ref.academic_year_id}); "
                    "falling back to "
                    f"{parse_ref.agreement_id} "
                    f"({parse_ref.academic_year_label or parse_ref.academic_year_id}) "
                    f"for {ref.cc_name}."
                )
                try:
                    _emit(
                        f"[{index}/{total_refs}] Fetching fallback artifact for "
                        f"{parse_ref.cc_name} agreement {parse_ref.agreement_id}."
                    )
                    pdf_path, downloaded = _fetch_with_status(parse_ref)
                    if downloaded:
                        download_count += 1
                    else:
                        cache_hit_count += 1
                except Exception:
                    _emit(
                        "Fallback artifact fetch failed "
                        f"for {ref.cc_name} agreement {parse_ref.agreement_id}; skipping."
                    )
                    continue
            raw_text = extract_text_from_pdf(pdf_path)
            parsed_rows = parse_articulation_rows(parse_ref, raw_text)
            _emit(
                f"[{index}/{total_refs}] Parsed {len(parsed_rows)} articulation rows "
                f"for {parse_ref.cc_name} agreement {parse_ref.agreement_id}."
            )
            all_rows.extend(parsed_rows)
        except Exception as err:
            _emit(
                "Failed to parse/store artifact "
                f"for {ref.cc_name} agreement {parse_ref.agreement_id}: "
                f"{type(err).__name__}; skipping."
            )
            # Keep ingest resilient for v1; problematic artifacts can be retried later.
            continue

    _emit(
        "Artifact fetch stats: "
        f"downloaded={download_count}, cache_hits={cache_hit_count}."
    )

    pre_normalize_count = len(all_rows)
    all_rows = filter_empty_course_codes(dedupe_rows(all_rows))
    _emit(
        "Normalization complete: "
        f"{pre_normalize_count} parsed rows -> {len(all_rows)} unique non-empty rows."
    )

    ensure_db(db_path)
    run = IngestRun.create(
        target_school=target_school,
        target_major=major_name,
        agreements_seen=len(refs),
        rows_written=0,
    )
    save_run(db_path, run)
    inserted = save_rows(db_path, run.run_id, all_rows)
    _emit(
        f"Persisted run {run.run_id}: agreements_seen={run.agreements_seen}, "
        f"rows_written={inserted}."
    )
    finalized = IngestRun(
        run_id=run.run_id,
        created_at_utc=run.created_at_utc,
        target_school=run.target_school,
        target_major=run.target_major,
        agreements_seen=run.agreements_seen,
        rows_written=inserted,
    )
    save_run(db_path, finalized)
    _emit(
        f"Ingest complete for target='{target_school}' major='{major_name}'."
    )
    return finalized

