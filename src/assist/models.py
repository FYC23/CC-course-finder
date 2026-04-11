from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Institution:
    id: int
    name: str
    is_community_college: bool


@dataclass(frozen=True)
class AgreementRef:
    target_school_id: int
    target_school_name: str
    target_major: str
    cc_id: int
    cc_name: str
    academic_year_id: int
    academic_year_label: str | None
    agreement_id: str
    artifact_url: str
    fallback_academic_year_id: int | None = None
    fallback_academic_year_label: str | None = None
    fallback_agreement_id: str | None = None
    fallback_artifact_url: str | None = None


@dataclass(frozen=True)
class ArticulationRow:
    target_school: str
    target_major: str
    target_requirement: str
    uc_equivalent: str
    cc_name: str
    cc_id: int
    course_code: str
    course_title: str
    agreement_id: str
    academic_year: str
    source_url: str
    notes: str = ""
    raw_text: str = ""


@dataclass(frozen=True)
class IngestRun:
    run_id: str
    created_at_utc: str
    target_school: str
    target_major: str
    agreements_seen: int
    rows_written: int

    @classmethod
    def create(
        cls,
        target_school: str,
        target_major: str,
        agreements_seen: int,
        rows_written: int,
    ) -> "IngestRun":
        created_at = datetime.now(tz=timezone.utc).isoformat()
        run_id = created_at.replace(":", "").replace("-", "").replace(".", "")
        return cls(
            run_id=run_id,
            created_at_utc=created_at,
            target_school=target_school,
            target_major=target_major,
            agreements_seen=agreements_seen,
            rows_written=rows_written,
        )

