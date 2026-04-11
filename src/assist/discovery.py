from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

from .http import AssistHttpClient
from .models import AgreementRef, Institution


class AssistDiscoveryError(RuntimeError):
    pass


class AssistDiscovery:
    def __init__(
        self,
        client: AssistHttpClient,
        category_code: str = "major",
        allow_non_numeric_keys: bool = False,
    ) -> None:
        self.client = client
        self.category_code = category_code
        self.allow_non_numeric_keys = allow_non_numeric_keys

    def get_institutions(self) -> list[Institution]:
        rows = self.client.get_json(f"{self.client.api_prefix}/institutions")
        institutions: list[Institution] = []
        for row in rows:
            names = row.get("names") or []
            if not names:
                continue
            institutions.append(
                Institution(
                    id=int(row["id"]),
                    name=str(names[0]["name"]),
                    is_community_college=bool(row.get("isCommunityCollege", False)),
                )
            )
        return institutions

    def resolve_school(self, school_name: str) -> Institution:
        school_name_lc = school_name.strip().lower()
        institutions = self.get_institutions()
        exact = [i for i in institutions if i.name.lower() == school_name_lc]
        if exact:
            return exact[0]

        partial = [i for i in institutions if school_name_lc in i.name.lower()]
        if len(partial) == 1:
            return partial[0]
        if not partial:
            raise AssistDiscoveryError(f"No institution found for '{school_name}'.")

        names = ", ".join(i.name for i in partial[:8])
        raise AssistDiscoveryError(
            f"Ambiguous institution '{school_name}'. Candidates: {names}"
        )

    def get_year_labels(self) -> dict[int, str]:
        rows = self.client.get_json(f"{self.client.api_prefix}/academicYears")
        labels: dict[int, str] = {}
        for row in rows:
            row_id = row.get("id")
            if row_id is None:
                continue
            # These keys have varied over time, so keep a permissive lookup.
            label = (
                row.get("code")
                or row.get("name")
                or row.get("description")
                or str(row_id)
            )
            labels[int(row_id)] = str(label)
        return labels

    def _agreement_candidates(self, target_school_id: int) -> Iterable[dict]:
        return self.client.get_json(
            f"{self.client.api_prefix}/institutions/{target_school_id}/agreements"
        )

    def _reports_for_pair(
        self,
        target_school_id: int,
        cc_id: int,
        year_id: int,
    ) -> list[dict]:
        path = (
            f"{self.client.api_prefix}/agreements"
            f"?receivingInstitutionId={target_school_id}"
            f"&sendingInstitutionId={cc_id}"
            f"&academicYearId={year_id}"
            f"&categoryCode={self.category_code}"
        )
        response = self.client.get_json(path)
        return list(response.get("reports", []))

    @staticmethod
    def _normalize_major_label(value: str) -> str:
        lowered = value.strip().lower()
        return "".join(ch for ch in lowered if ch.isalnum())

    def _major_matches(self, report_label: str, requested_major: str) -> bool:
        report_label = report_label.strip()
        requested_major = requested_major.strip()
        if not report_label or not requested_major:
            return False
        if report_label.lower() == requested_major.lower():
            return True

        normalized_report = self._normalize_major_label(report_label)
        normalized_requested = self._normalize_major_label(requested_major)

        # Support common ASSIST label suffixes like "/B.S." and "/B.A." while
        # avoiding false positives like "Computer Science and Engineering".
        report_base = report_label.split("/", 1)[0]
        normalized_report_base = self._normalize_major_label(report_base)
        if normalized_report_base == normalized_requested:
            return True
        return False

    def discover_major_agreements(
        self,
        target_school_name: str,
        major_name: str,
        max_community_colleges: int | None = None,
    ) -> list[AgreementRef]:
        target_school = self.resolve_school(target_school_name)
        institutions_by_id = {i.id: i.name for i in self.get_institutions()}
        year_labels = self.get_year_labels()
        refs_by_cc: dict[int, AgreementRef] = {}
        cc_order: list[int] = []

        agreement_candidates = list(self._agreement_candidates(target_school.id))
        for candidate in agreement_candidates:
            if not candidate.get("isCommunityCollege", False):
                continue
            cc_id = int(candidate["institutionParentId"])
            cc_name = str(
                candidate.get("institutionParentName")
                or institutions_by_id.get(cc_id)
                or str(cc_id)
            )
            sending_years = candidate.get("sendingYearIds") or []
            if not sending_years:
                continue
            candidate_years = sorted({int(y) for y in sending_years}, reverse=True)
            selected = self._select_best_match_for_candidate(
                target_school_id=target_school.id,
                cc_id=cc_id,
                candidate_years=candidate_years,
                major_name=major_name,
            )
            if not selected:
                continue
            selected_year_id, agreement_id, fallback = selected
            ref = AgreementRef(
                target_school_id=target_school.id,
                target_school_name=target_school.name,
                target_major=major_name,
                cc_id=cc_id,
                cc_name=cc_name,
                academic_year_id=selected_year_id,
                academic_year_label=year_labels.get(selected_year_id),
                agreement_id=agreement_id,
                artifact_url=f"{self.client.api_prefix}/artifacts/{agreement_id}",
                fallback_academic_year_id=fallback[0] if fallback else None,
                fallback_academic_year_label=(
                    year_labels.get(fallback[0]) if fallback else None
                ),
                fallback_agreement_id=fallback[1] if fallback else None,
                fallback_artifact_url=(
                    f"{self.client.api_prefix}/artifacts/{fallback[1]}"
                    if fallback
                    else None
                ),
            )
            previous = refs_by_cc.get(cc_id)
            if previous is None:
                refs_by_cc[cc_id] = ref
                cc_order.append(cc_id)
                continue
            if self._is_better_ref(candidate=ref, incumbent=previous):
                refs_by_cc[cc_id] = ref

        refs = [refs_by_cc[cc_id] for cc_id in cc_order]
        if max_community_colleges is not None:
            refs = refs[:max_community_colleges]
        return refs

    def _select_best_match_for_candidate(
        self,
        target_school_id: int,
        cc_id: int,
        candidate_years: list[int],
        major_name: str,
    ) -> tuple[int, str, tuple[int, str] | None] | None:
        selected: tuple[int, str, str] | None = None
        numeric_fallback: tuple[int, str, str] | None = None
        for year_id in candidate_years:
            reports = self._reports_for_pair(target_school_id, cc_id, year_id)
            year_non_numeric: tuple[int, str, str] | None = None
            year_numeric: tuple[int, str, str] | None = None
            for report in reports:
                report_label = str(report.get("label", "")).strip()
                if not self._major_matches(report_label, major_name):
                    continue
                agreement_id = str(report.get("key", "")).strip()
                if not agreement_id:
                    continue
                if agreement_id.isdigit():
                    year_numeric = year_numeric or (year_id, report_label, agreement_id)
                else:
                    year_non_numeric = year_non_numeric or (
                        year_id,
                        report_label,
                        agreement_id,
                    )

            if year_numeric and not numeric_fallback:
                numeric_fallback = year_numeric

            if not selected:
                if self.allow_non_numeric_keys and year_non_numeric:
                    selected = year_non_numeric
                elif year_numeric:
                    selected = year_numeric
                elif year_non_numeric:
                    selected = year_non_numeric

            if not self.allow_non_numeric_keys and numeric_fallback:
                selected = numeric_fallback
                break
            if (
                self.allow_non_numeric_keys
                and selected
                and (selected[2].isdigit() or numeric_fallback)
            ):
                break

        if not selected:
            return None
        if not self.allow_non_numeric_keys:
            if not numeric_fallback:
                return None
            selected = numeric_fallback
            numeric_fallback = None

        selected_year_id, _, agreement_id = selected
        fallback: tuple[int, str] | None = None
        if self.allow_non_numeric_keys and not agreement_id.isdigit() and numeric_fallback:
            fallback = (numeric_fallback[0], numeric_fallback[2])
        return (selected_year_id, agreement_id, fallback)

    def _is_better_ref(self, candidate: AgreementRef, incumbent: AgreementRef) -> bool:
        if candidate.academic_year_id != incumbent.academic_year_id:
            return candidate.academic_year_id > incumbent.academic_year_id
        if self.allow_non_numeric_keys:
            if not candidate.agreement_id.isdigit() and incumbent.agreement_id.isdigit():
                return True
            if candidate.agreement_id.isdigit() and not incumbent.agreement_id.isdigit():
                return False
        else:
            if candidate.agreement_id.isdigit() and not incumbent.agreement_id.isdigit():
                return True
            if not candidate.agreement_id.isdigit() and incumbent.agreement_id.isdigit():
                return False
        return False

    @staticmethod
    def serialize_refs(refs: list[AgreementRef]) -> list[dict]:
        return [asdict(r) for r in refs]

