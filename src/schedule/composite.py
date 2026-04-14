from __future__ import annotations

from .banner_ellucian import BannerEllucianProvider
from .banner_ssb_classic import BannerSsbClassicProvider
from .marin_colleague import MarinColleagueProvider
from .models import CollegeScheduleSource, CourseAvailability
from .providers import ScheduleProvider
from .smcccd_colleague import SmcccdColleagueProvider
from .term import ParsedTerm
from .vsb_4cd import Vsb4cdProvider
from .wvm_static import WvmStaticProvider


class CompositeProvider:
    def __init__(self, providers: list[ScheduleProvider]) -> None:
        self._providers = providers

    def supports_source(self, source: CollegeScheduleSource) -> bool:
        return any(p.supports_source(source) for p in self._providers)

    def search_course(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, course_code: str
    ) -> CourseAvailability:
        for p in self._providers:
            if p.supports_source(source):
                return p.search_course(source=source, term=term, course_code=course_code)
        raise ValueError(f"No provider for system={source.system!r}")


def build_composite_provider() -> CompositeProvider:
    return CompositeProvider([
        BannerEllucianProvider(),
        BannerSsbClassicProvider(),
        WvmStaticProvider(),
        Vsb4cdProvider(),
        MarinColleagueProvider(),
        SmcccdColleagueProvider(),
    ])
