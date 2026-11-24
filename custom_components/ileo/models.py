"""Data models and exceptions of the Iléo client (no Home Assistant dependency)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class IleoContract:
    """A water contract attached to an Iléo customer account."""

    number: str
    label: str = ""
    """Name given to the contract by the subscriber, if any."""


@dataclass(frozen=True, slots=True)
class IleoReading:
    """One daily reading from the Iléo export.

    `day` is the day the water was consumed. Volumes are in litres.
    """

    day: date
    index: float | None = None
    """Meter index at the end of the day, in litres."""
    consumption: float | None = None
    """Consumption of the day as given by the export, in litres."""


class IleoError(Exception):
    """Base error of the Iléo client."""


class IleoConnectionError(IleoError):
    """The Iléo portal is unreachable or answered with a server error."""


class IleoAuthError(IleoError):
    """The Iléo portal rejected the credentials."""


class IleoResponseError(IleoError):
    """The portal answered, but not with what was expected."""


class IleoContractError(IleoResponseError):
    """The expected contract is not attached to the account."""


class IleoParseError(IleoResponseError):
    """The consumption export could not be parsed."""
