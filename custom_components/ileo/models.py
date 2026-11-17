"""Modèles de données et exceptions du client Iléo (sans dépendance à Home Assistant)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class IleoReading:
    """Un relevé journalier issu de l'export Iléo.

    `day` est le jour de consommation. Les volumes sont exprimés en litres.
    """

    day: date
    index: float | None = None
    """Index du compteur en fin de journée, en litres."""
    consumption: float | None = None
    """Consommation du jour telle que fournie par l'export, en litres."""


class IleoError(Exception):
    """Erreur générique du client Iléo."""


class IleoConnectionError(IleoError):
    """Le portail Iléo est injoignable ou a répondu par une erreur serveur."""


class IleoAuthError(IleoError):
    """Identifiants refusés par le portail Iléo."""


class IleoResponseError(IleoError):
    """Le portail a répondu, mais pas avec ce qui était attendu."""


class IleoParseError(IleoResponseError):
    """L'export de consommation n'a pas pu être interprété."""
