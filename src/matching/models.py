"""Alias records: an ASSIST code a college now lists under another code, with provenance."""
from __future__ import annotations

from dataclasses import dataclass

from .codes import code_key

ALIAS_STATUSES: tuple[str, ...] = ("verified", "accepted", "review", "rejected")
# verified: a published crosswalk, a catalog note, or a human approved it.
# accepted: a decision backend was above the accept threshold; used at query time.
# review:   between thresholds; waits for `matching approve` / `matching reject`.
# rejected: below the review threshold, or a human rejected it.
ACTIVE_STATUSES: frozenset[str] = frozenset({"verified", "accepted"})


@dataclass(frozen=True)
class CourseAlias:
    cc_id: int
    old_code: str
    new_code: str
    source: str
    status: str
    confidence: float = 1.0
    evidence: str = ""
    alias_id: int | None = None
    reviewed: bool = False

    def __post_init__(self) -> None:
        if self.status not in ALIAS_STATUSES:
            raise ValueError(f"status must be one of {ALIAS_STATUSES}, got {self.status!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be within [0, 1], got {self.confidence}")
        for name in ("old_code", "new_code", "source"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")

    @property
    def old_key(self) -> str:
        return code_key(self.old_code)

    @property
    def new_key(self) -> str:
        return code_key(self.new_code)


@dataclass(frozen=True)
class SubjectRename:
    """Every course in ``old_subject`` at this college is now listed under ``new_subject``."""

    cc_id: int
    old_subject: str
    new_subject: str
    source: str
    evidence: str = ""
