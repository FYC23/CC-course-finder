from __future__ import annotations

from typing import Any

from src.assist.discovery import AssistDiscovery


class FakeClient:
    def __init__(self) -> None:
        self.api_prefix = "/api"

    def get_json(self, path: str) -> Any:
        return self._get_json(path)

    def get_json_with_retry(self, path: str, *, timeout: int = 15, max_retries: int = 2) -> Any:
        return self._get_json(path)

    def _get_json(self, path: str) -> Any:
        if path == "/api/institutions":
            return [
                {
                    "id": 11,
                    "isCommunityCollege": False,
                    "names": [{"name": "University of California, Los Angeles"}],
                },
                {
                    "id": 54,
                    "isCommunityCollege": True,
                    "names": [{"name": "De Anza College"}],
                },
            ]
        if path == "/api/academicYears":
            return [{"id": 75, "code": "2024-2025"}]
        if path == "/api/institutions/11/agreements":
            return [
                {
                    "isCommunityCollege": True,
                    "institutionParentId": 54,
                    "institutionParentName": "De Anza College",
                    "sendingYearIds": [74, 75],
                }
            ]
        if path.startswith("/api/agreements?"):
            return {
                "reports": [
                    {"label": "Computer Science", "key": 12345678},
                    {"label": "Mathematics", "key": 9999},
                ]
            }
        raise AssertionError(f"Unexpected path: {path}")


class NonNumericKeyClient:
    def __init__(self) -> None:
        self.api_prefix = "/api"

    def get_json(self, path: str) -> Any:
        return self._get_json(path)

    def get_json_with_retry(self, path: str, *, timeout: int = 15, max_retries: int = 2) -> Any:
        return self._get_json(path)

    def _get_json(self, path: str) -> Any:
        if path == "/api/institutions":
            return [
                {
                    "id": 11,
                    "isCommunityCollege": False,
                    "names": [{"name": "University of California, Los Angeles"}],
                },
                {
                    "id": 54,
                    "isCommunityCollege": True,
                    "names": [{"name": "De Anza College"}],
                },
            ]
        if path == "/api/academicYears":
            return [
                {"id": 75, "code": "2024-2025"},
                {"id": 74, "code": "2023-2024"},
            ]
        if path == "/api/institutions/11/agreements":
            return [
                {
                    "isCommunityCollege": True,
                    "institutionParentId": 54,
                    "institutionParentName": "De Anza College",
                    "sendingYearIds": [74, 75],
                }
            ]
        if "academicYearId=75" in path:
            return {
                "reports": [
                    {
                        "label": "Computer Science/B.S.",
                        "key": "75/54/to/11/Major/abc 123",
                    }
                ]
            }
        if "academicYearId=74" in path:
            return {
                "reports": [
                    {"label": "Computer Science", "key": 12345678},
                ]
            }
        raise AssertionError(f"Unexpected path: {path}")


class MixedSameYearOrderClient:
    def __init__(self) -> None:
        self.api_prefix = "/api"

    def get_json(self, path: str) -> Any:
        return self._get_json(path)

    def get_json_with_retry(self, path: str, *, timeout: int = 15, max_retries: int = 2) -> Any:
        return self._get_json(path)

    def _get_json(self, path: str) -> Any:
        if path == "/api/institutions":
            return [
                {
                    "id": 11,
                    "isCommunityCollege": False,
                    "names": [{"name": "University of California, Los Angeles"}],
                },
                {
                    "id": 54,
                    "isCommunityCollege": True,
                    "names": [{"name": "De Anza College"}],
                },
            ]
        if path == "/api/academicYears":
            return [{"id": 75, "code": "2024-2025"}]
        if path == "/api/institutions/11/agreements":
            return [
                {
                    "isCommunityCollege": True,
                    "institutionParentId": 54,
                    "institutionParentName": "De Anza College",
                    "sendingYearIds": [75],
                }
            ]
        if "academicYearId=75" in path:
            return {
                "reports": [
                    {"label": "Computer Science", "key": 11111111},
                    {"label": "Computer Science/B.S.", "key": "75/54/to/11/Major/new"},
                ]
            }
        raise AssertionError(f"Unexpected path: {path}")


class DuplicateCandidateClient:
    def __init__(self) -> None:
        self.api_prefix = "/api"

    def get_json(self, path: str) -> Any:
        return self._get_json(path)

    def get_json_with_retry(self, path: str, *, timeout: int = 15, max_retries: int = 2) -> Any:
        return self._get_json(path)

    def _get_json(self, path: str) -> Any:
        if path == "/api/institutions":
            return [
                {
                    "id": 11,
                    "isCommunityCollege": False,
                    "names": [{"name": "University of California, Los Angeles"}],
                },
                {
                    "id": 54,
                    "isCommunityCollege": True,
                    "names": [{"name": "De Anza College"}],
                },
                {
                    "id": 55,
                    "isCommunityCollege": True,
                    "names": [{"name": "Foothill College"}],
                },
            ]
        if path == "/api/academicYears":
            return [
                {"id": 75, "code": "2024-2025"},
                {"id": 74, "code": "2023-2024"},
            ]
        if path == "/api/institutions/11/agreements":
            return [
                {
                    "isCommunityCollege": True,
                    "institutionParentId": 54,
                    "institutionParentName": "De Anza College",
                    "sendingYearIds": [74],
                },
                {
                    "isCommunityCollege": True,
                    "institutionParentId": 54,
                    "institutionParentName": "De Anza College",
                    "sendingYearIds": [75],
                },
                {
                    "isCommunityCollege": True,
                    "institutionParentId": 55,
                    "institutionParentName": "Foothill College",
                    "sendingYearIds": [75],
                },
            ]
        if "sendingInstitutionId=54" in path and "academicYearId=75" in path:
            return {"reports": [{"label": "Computer Science", "key": 33333333}]}
        if "sendingInstitutionId=54" in path and "academicYearId=74" in path:
            return {"reports": [{"label": "Computer Science", "key": 11111111}]}
        if "sendingInstitutionId=55" in path and "academicYearId=75" in path:
            return {"reports": [{"label": "Computer Science", "key": 22222222}]}
        raise AssertionError(f"Unexpected path: {path}")


def test_discover_major_agreements_returns_expected_shape() -> None:
    discovery = AssistDiscovery(client=FakeClient())
    refs = discovery.discover_major_agreements(
        target_school_name="University of California, Los Angeles",
        major_name="Computer Science",
        max_community_colleges=5,
    )
    assert len(refs) == 1
    ref = refs[0]
    assert ref.cc_name == "De Anza College"
    assert ref.cc_id == 54
    assert ref.agreement_id == "12345678"
    assert ref.academic_year_label == "2024-2025"
    assert ref.artifact_url == "/api/artifacts/12345678"


def test_discover_major_agreements_accepts_non_numeric_latest_key() -> None:
    discovery = AssistDiscovery(
        client=NonNumericKeyClient(), allow_non_numeric_keys=True
    )
    refs = discovery.discover_major_agreements(
        target_school_name="University of California, Los Angeles",
        major_name="Computer Science",
        max_community_colleges=5,
    )
    assert len(refs) == 1
    ref = refs[0]
    assert ref.academic_year_id == 75
    assert ref.agreement_id == "75/54/to/11/Major/abc 123"
    assert ref.artifact_url == "/api/artifacts/75/54/to/11/Major/abc 123"
    assert ref.fallback_academic_year_id == 74
    assert ref.fallback_agreement_id == "12345678"
    assert ref.fallback_artifact_url == "/api/artifacts/12345678"


def test_discover_major_agreements_defaults_to_numeric_key() -> None:
    discovery = AssistDiscovery(client=NonNumericKeyClient())
    refs = discovery.discover_major_agreements(
        target_school_name="University of California, Los Angeles",
        major_name="Computer Science",
        max_community_colleges=5,
    )
    assert len(refs) == 1
    ref = refs[0]
    assert ref.academic_year_id == 74
    assert ref.agreement_id == "12345678"
    assert ref.fallback_agreement_id is None


def test_discover_major_agreements_prefers_non_numeric_in_same_year() -> None:
    discovery = AssistDiscovery(
        client=MixedSameYearOrderClient(), allow_non_numeric_keys=True
    )
    refs = discovery.discover_major_agreements(
        target_school_name="University of California, Los Angeles",
        major_name="Computer Science",
        max_community_colleges=5,
    )
    assert len(refs) == 1
    ref = refs[0]
    assert ref.academic_year_id == 75
    assert ref.agreement_id == "75/54/to/11/Major/new"
    assert ref.fallback_agreement_id == "11111111"


def test_discover_major_agreements_dedupes_duplicate_candidates_by_cc() -> None:
    discovery = AssistDiscovery(client=DuplicateCandidateClient())
    refs = discovery.discover_major_agreements(
        target_school_name="University of California, Los Angeles",
        major_name="Computer Science",
        max_community_colleges=5,
    )
    assert len(refs) == 2
    de_anza = next(r for r in refs if r.cc_id == 54)
    assert de_anza.agreement_id == "33333333"


def test_discover_major_agreements_limits_unique_ccs_not_raw_candidates() -> None:
    discovery = AssistDiscovery(client=DuplicateCandidateClient())
    refs = discovery.discover_major_agreements(
        target_school_name="University of California, Los Angeles",
        major_name="Computer Science",
        max_community_colleges=1,
    )
    assert len(refs) == 1
    assert refs[0].cc_id == 54

