"""Exception types shared by schedule adapters and the replay engine."""
from __future__ import annotations


class ScheduleLookupError(Exception):
    """A lookup failed for a reason the adapter understands (not a plain network error)."""


class PortalChanged(ScheduleLookupError):
    """The portal answered, but not in the shape the adapter or spec expects."""


class SpecInvalid(ValueError):
    """A replay spec file failed validation. The message names the file and the field."""
