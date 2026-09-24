from __future__ import annotations

from .colleague_selfservice import ColleagueSelfServiceProvider
from .banner9_ssb import Banner9SsbProvider
from .generic_replay import GenericReplayProvider
from .listing import ListedCourse, ListingUnsupported
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

    def list_subject(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, subject: str
    ) -> tuple[ListedCourse, ...]:
        for p in self._providers:
            if p.supports_source(source):
                lister = getattr(p, "list_subject", None)
                if lister is None:
                    raise ListingUnsupported(
                        f"system={source.system!r} cannot list a whole subject (cc_id={source.cc_id})"
                    )
                return lister(source=source, term=term, subject=subject)
        raise ValueError(f"No provider for system={source.system!r}")


def build_composite_provider() -> CompositeProvider:
    return CompositeProvider([
        ColleagueSelfServiceProvider(),
        Banner9SsbProvider(),
        WvmStaticProvider(),
        Vsb4cdProvider(),
        MarinColleagueProvider(),
        SmcccdColleagueProvider(),
        GenericReplayProvider(),
    ])
