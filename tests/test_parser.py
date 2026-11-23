"""Tests of the export parser: anonymized real format and synthetic variants."""

from __future__ import annotations

from datetime import date
from itertools import pairwise

import pytest

from custom_components.ileo.models import IleoParseError, IleoReading
from custom_components.ileo.parser import decode_export, parse_export_csv

from .conftest import load_fixture_bytes


def test_real_export() -> None:
    """Real format: index in litres without a unit, empty "écoulement permanent"."""
    readings = parse_export_csv(
        decode_export(load_fixture_bytes("export_real_anonymized.csv"))
    )
    assert readings[0] == IleoReading(
        date(2026, 11, 18), index=100000.0, consumption=85.0
    )
    assert readings[-1] == IleoReading(
        date(2026, 11, 22), index=100603.0, consumption=182.0
    )
    # Consistency observed on the portal: index(D) − index(D−1) = consumption(D).
    for previous, current in pairwise(readings):
        assert current.index - previous.index == current.consumption


def test_export_with_index_and_consumption() -> None:
    readings = parse_export_csv(
        decode_export(load_fixture_bytes("export_synthetic.csv"))
    )
    assert readings[0] == IleoReading(
        date(2026, 11, 1), index=123456.0, consumption=None
    )
    assert readings[1] == IleoReading(
        date(2026, 11, 2), index=123701.0, consumption=245.0
    )
    assert [r.day.day for r in readings] == [1, 2, 3, 4, 5]


def test_export_with_consumption_only_and_preamble() -> None:
    readings = parse_export_csv(
        decode_export(load_fixture_bytes("export_synthetic_consumption_only.csv"))
    )
    # The duplicate of 02/11 keeps the last value, the empty line of 03/11 is skipped.
    assert readings == [
        IleoReading(date(2026, 11, 1), index=None, consumption=210.0),
        IleoReading(date(2026, 11, 2), index=None, consumption=199.0),
    ]


def test_windows_1252_and_thousands_separators() -> None:
    raw = "Date relevé;Index (L);Volume (m3)\n03/11/26;1 234 567;0,25\n".encode(
        "cp1252"
    )
    assert parse_export_csv(decode_export(raw)) == [
        IleoReading(date(2026, 11, 3), index=1234567.0, consumption=250.0)
    ]


def test_non_breaking_thousands_separators() -> None:
    text = "date;index\n2026-11-03;1 234 567\n"
    assert parse_export_csv(text)[0].index == 1234567.0


def test_comma_separator_and_sorting() -> None:
    # Index without a unit: litres, as in the real export.
    text = 'date,index\n"2026-11-02",10500\n"2026-11-01",10200\n'
    readings = parse_export_csv(text)
    assert [(r.day.day, r.index) for r in readings] == [(1, 10200.0), (2, 10500.0)]


@pytest.mark.parametrize(
    "text", ["", "<html>Erreur</html>", "Jour;Valeur\n01/11/2026;3\n"]
)
def test_header_not_found(text: str) -> None:
    with pytest.raises(IleoParseError):
        parse_export_csv(text)


def test_utf8_bom() -> None:
    raw = "﻿Date;Consommation (L)\n01/11/2026;12\n".encode()
    assert parse_export_csv(decode_export(raw))[0].consumption == 12.0


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "1e999", "-12", "abc"])
def test_absurd_values_ignored(value: str) -> None:
    """A negative or non-finite value must never reach the statistics."""
    text = f"date;consommation (litres);index\n2026-11-18;{value};{value}\n"
    assert parse_export_csv(text) == []
    text = f"date;consommation (litres);index\n2026-11-18;{value};100\n"
    assert parse_export_csv(text) == [
        IleoReading(date(2026, 11, 18), index=100.0, consumption=None)
    ]


def test_index_without_unit_follows_consumption() -> None:
    """If the export switches to m³, so does the index (no unit in its header)."""
    text = "date;consommation (m3);index\n2026-11-18;0,085;100,25\n"
    assert parse_export_csv(text) == [
        IleoReading(date(2026, 11, 18), index=100250.0, consumption=85.0)
    ]


def test_short_and_undated_lines_skipped() -> None:
    text = "consommation (litres);date\n12\n34;total\n56;2026-11-18\n"
    assert parse_export_csv(text) == [
        IleoReading(date(2026, 11, 18), index=None, consumption=56.0)
    ]
