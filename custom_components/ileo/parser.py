"""Parsing of the Iléo consumption CSV export.

Format observed on the portal (November 2026), UTF-8, LF line endings:

    date;consommation (litres);écoulement permanent (litres);index
    2026-11-18;85; ;100000

- `date`: day the water was consumed (YYYY-MM-DD);
- `consommation`: volume of the day, in litres;
- `écoulement permanent`: often empty (a single space), ignored;
- `index`: meter index **in litres** at the end of the day, with no unit in the
  header (index(D) − index(D−1) = consumption(D)).

The parser stays tolerant to likely variations:

- `;`, tab or `,` separator (detected on the header line);
- preamble lines skipped until the header is found (a "date" column and at
  least an "index" or "consommation"/"volume" column);
- `DD/MM/YYYY`, `DD/MM/YY`, `DD-MM-YYYY` or `YYYY-MM-DD` dates (time ignored);
- decimal comma or point, thousands spaces accepted;
- unit read from the header (`m3`, `m³`, `L`, `litres`); an index without a
  unit follows the consumption column, else the defaults below apply;
- several lines for the same day: the last one wins.

The export is external data: negative or non-finite values (`nan`, `inf`) are
ignored, so that they can never reach the statistics.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
import io
import math
import re
import unicodedata

from .models import IleoParseError, IleoReading

# Units assumed when the header does not give them (observed: litres for both).
DEFAULT_INDEX_FACTOR = 1.0
DEFAULT_CONSUMPTION_FACTOR = 1.0

_DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d")
_CONSUMPTION_WORDS = ("consommation", "conso", "volume")
_LITRE_RE = re.compile(r"(\(l\)|\blitres?\b|\bl\b)")
_SPACES_RE = re.compile(r"[\s  ]")


def decode_export(raw: bytes) -> str:
    """Decode the export (UTF-8 with or without BOM, else Windows-1252)."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _normalize(text: str) -> str:
    """Lower case, without accents, `m³` → `m3`."""
    text = text.replace("³", "3").strip().lower()
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def _unit_factor(header: str) -> float | None:
    """Factor to litres from the unit in the header, None if there is none."""
    if "m3" in header:
        return 1000.0
    if _LITRE_RE.search(header):
        return 1.0
    return None


def _parse_number(value: str) -> float | None:
    """Finite positive number, or None if the cell is empty or absurd."""
    cleaned = _SPACES_RE.sub("", value)
    if not cleaned or cleaned in {"-", "--"}:
        return None
    try:
        number = float(cleaned.replace(",", "."))
    except ValueError:
        return None
    return number if math.isfinite(number) and number >= 0 else None


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
    """Turn the export text into daily readings sorted by day."""
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
        raise IleoParseError("Header of the export not found")

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
    conso_unit = _unit_factor(headers[conso_col]) if conso_col is not None else None
    index_unit = _unit_factor(headers[index_col]) if index_col is not None else None
    conso_factor = conso_unit or DEFAULT_CONSUMPTION_FACTOR
    # The real index header has no unit: it follows the consumption column.
    index_factor = index_unit or conso_unit or DEFAULT_INDEX_FACTOR

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
