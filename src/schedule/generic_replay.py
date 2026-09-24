"""ScheduleProvider that replays a recorded per-college spec (system == "replay").

Specs are data files under src/schedule/data/specs/. The provider builds placeholder
values from the term and course code, runs the spec's HTTP steps through a
ReplayExecutor (one per provider instance, so one HTTP session and response cache per
college per search), and extracts sections with the spec's extract block.
"""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

import requests

from .models import CollegeScheduleSource, CourseAvailability
from .replay.executor import ReplayExecutor
from .replay.extractor import extract_sections
from .replay.inputs import build_values
from .replay.registry import load_all_specs
from .replay.spec import ReplaySpec
from .term import ParsedTerm

REPLAY_SYSTEM = "replay"


class GenericReplayProvider:
    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        executor: ReplayExecutor | None = None,
        specs: Mapping[int, ReplaySpec] | None = None,
    ) -> None:
        self._executor = executor or ReplayExecutor(session)
        self._specs = specs if specs is not None else load_all_specs()

    def supports_source(self, source: CollegeScheduleSource) -> bool:
        return source.system == REPLAY_SYSTEM and source.cc_id in self._specs

    def search_course(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, course_code: str
    ) -> CourseAvailability:
        if not self.supports_source(source):
            raise ValueError(
                f"GenericReplayProvider does not support system={source.system!r} cc_id={source.cc_id}"
            )
        spec = self._specs[source.cc_id]
        values = build_values(spec.inputs, term, course_code)
        result = self._executor.execute(spec, term=term, values=values)
        scope = MappingProxyType({**values, **result.captures})
        sections = extract_sections(result.bodies, spec.extract, scope)
        return CourseAvailability(
            cc_id=source.cc_id,
            cc_name=source.cc_name,
            term=term.label,
            course_code=course_code,
            offered=bool(sections),
            sections=list(sections),
            source_url=result.final_url or source.base_url,
            raw_summary=(
                f"{len(sections)} section(s) via replay spec cc_id={spec.cc_id} "
                f"v{spec.version} ({len(result.bodies)} page(s))"
            ),
        )
