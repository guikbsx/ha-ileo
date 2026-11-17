"""Lecture de l'export CSV de consommation Iléo.

⚠️ HYPOTHÈSE : le format exact de l'export n'a pas encore été observé (étape 2).
Le parseur est donc volontairement tolérant :

- séparateur `;`, tabulation ou `,` (détecté sur la ligne d'en-tête) ;
- lignes de préambule ignorées jusqu'à trouver l'en-tête (une colonne « date »
  et au moins une colonne « index » ou « consommation »/« volume ») ;
- dates `JJ/MM/AAAA`, `JJ/MM/AA`, `JJ-MM-AAAA` ou `AAAA-MM-JJ` (heure éventuelle ignorée) ;
- nombres à virgule ou à point, espaces de milliers acceptés ;
- unité lue dans l'en-tête (`m3`, `m³`, `L`, `litres`), sinon valeurs par défaut
  ci-dessous ;
- plusieurs lignes pour le même jour : la dernière l'emporte.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
import io
import re
import unicodedata

from .models import IleoParseError, IleoReading

# HYPOTHÈSE : unités utilisées quand l'en-tête ne les précise pas.
DEFAULT_INDEX_FACTOR = 1000.0  # index exprimé en m³
DEFAULT_CONSUMPTION_FACTOR = 1.0  # consommation exprimée en litres

_DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d")
_CONSUMPTION_WORDS = ("consommation", "conso", "volume")
_LITRE_RE = re.compile(r"(\(l\)|\blitres?\b|\bl\b)")


def decode_export(raw: bytes) -> str:
    """Décode l'export (UTF-8 avec ou sans BOM, sinon Windows-1252)."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _normalize(text: str) -> str:
    """Minuscules, sans accents, `m³` → `m3`."""
    text = text.replace("³", "3").strip().lower()
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def _unit_factor(header: str, default: float) -> float:
    if "m3" in header:
        return 1000.0
    if _LITRE_RE.search(header):
        return 1.0
    return default


def _parse_number(value: str) -> float | None:
    cleaned = re.sub(r"[\s  ]", "", value)
    if not cleaned or cleaned in {"-", "--"}:
        return None
    cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(value: str) -> date | None:
    token = value.strip().split(" ")[0].split("T")[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None


def _cell_litres(row: list[str], col: int | None, factor: float) -> float | None:
    if col is None or col >= len(row):
        return None
    value = _parse_number(row[col])
    return None if value is None else round(value * factor, 3)


def _guess_delimiter(line: str) -> str:
    for delimiter in (";", "\t"):
        if delimiter in line:
            return delimiter
    return ","


def _is_header(cells: list[str]) -> bool:
    normalized = [_normalize(c) for c in cells]
    has_date = any("date" in c for c in normalized)
    has_value = any(
        "index" in c or any(w in c for w in _CONSUMPTION_WORDS) for c in normalized
    )
    return has_date and has_value


def parse_export_csv(text: str) -> list[IleoReading]:
    """Transforme le texte de l'export en relevés journaliers triés par date."""
    lines = text.splitlines()
    header_pos: int | None = None
    delimiter = ";"
    for pos, line in enumerate(lines):
        if not line.strip():
            continue
        delimiter = _guess_delimiter(line)
        cells = next(csv.reader([line], delimiter=delimiter))
        if _is_header(cells):
            header_pos = pos
            break
    if header_pos is None:
        raise IleoParseError("En-tête de l'export introuvable")

    reader = csv.reader(io.StringIO("\n".join(lines[header_pos:])), delimiter=delimiter)
    headers = [_normalize(h) for h in next(reader)]

    date_col = next(i for i, h in enumerate(headers) if "date" in h)
    index_col = next((i for i, h in enumerate(headers) if "index" in h), None)
    conso_col = next(
        (
            i
            for i, h in enumerate(headers)
            if i != index_col and any(w in h for w in _CONSUMPTION_WORDS)
        ),
        None,
    )
    index_factor = (
        _unit_factor(headers[index_col], DEFAULT_INDEX_FACTOR)
        if index_col is not None
        else 1.0
    )
    conso_factor = (
        _unit_factor(headers[conso_col], DEFAULT_CONSUMPTION_FACTOR)
        if conso_col is not None
        else 1.0
    )

    by_day: dict[date, IleoReading] = {}
    for row in reader:
        if len(row) <= date_col:
            continue
        day = _parse_date(row[date_col])
        if day is None:
            continue
        index = _cell_litres(row, index_col, index_factor)
        consumption = _cell_litres(row, conso_col, conso_factor)
        if index is None and consumption is None:
            continue
        by_day[day] = IleoReading(day=day, index=index, consumption=consumption)

    return [by_day[day] for day in sorted(by_day)]
