from __future__ import annotations

from src.schedule.catalog import get_college_source
from src.schedule.pilot_evergreen import EvergreenBannerProvider
from src.schedule.term import parse_term_label


class _FakeResponse:
    def __init__(self, text: str, url: str) -> None:
        self.text = text
        self.url = url

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, params: dict[str, str], timeout: int) -> _FakeResponse:
        self.calls.append((url, params))
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return _FakeResponse(self.text, f"{url}?{query}")


def test_pilot_provider_maps_term_and_parses_sections() -> None:
    source = get_college_source(2)
    session = _FakeSession(
        text=(
            "CRN:12345|STATUS:Open|MODALITY:Online|TITLE:Calculus II|INSTRUCTOR:Ada\n"
            "CRN:12346|STATUS:Closed|MODALITY:In Person|TITLE:Calculus II|INSTRUCTOR:Bob"
        )
    )
    provider = EvergreenBannerProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 1B"
    )

    assert out.offered is True
    assert len(out.sections) == 2
    assert out.sections[0].modality == "online"
    assert out.sections[1].status == "closed"
    assert session.calls[0][1]["Terms"] == "2026SU"
    assert session.calls[0][1]["locations"] == "EVC"
    assert session.calls[0][1]["keyword"] == "MATH 1B"


def test_pilot_provider_handles_missing_course() -> None:
    source = get_college_source(2)
    session = _FakeSession(text="No matching sections")
    provider = EvergreenBannerProvider(session=session)

    out = provider.search_course(
        source=source, term=parse_term_label("Summer 2026"), course_code="MATH 1B"
    )
    assert out.offered is False
    assert out.sections == []
