"""Tests du parseur d'export (formats HYPOTHÉTIQUES)."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.ileo.models import IleoParseError, IleoReading
from custom_components.ileo.parser import decode_export, parse_export_csv

from .conftest import load_fixture_bytes


def test_export_index_et_consommation() -> None:
    readings = parse_export_csv(
        decode_export(load_fixture_bytes("export_hypothetique.csv"))
    )
    assert readings[0] == IleoReading(
        date(2026, 11, 1), index=123456.0, consumption=None
    )
    assert readings[1] == IleoReading(
        date(2026, 11, 2), index=123701.0, consumption=245.0
    )
    assert [r.day.day for r in readings] == [1, 2, 3, 4, 5]


def test_export_consommation_seule_avec_preambule() -> None:
    readings = parse_export_csv(
        decode_export(load_fixture_bytes("export_hypothetique_consommation_seule.csv"))
    )
    # Le doublon du 02/11 garde la dernière valeur, la ligne vide du 03/11 est ignorée.
    assert readings == [
        IleoReading(date(2026, 11, 1), index=None, consumption=210.0),
        IleoReading(date(2026, 11, 2), index=None, consumption=199.0),
    ]


def test_decodage_windows_1252_et_milliers() -> None:
    raw = "Date relevé;Index (L);Volume (m3)\n03/11/26;1 234 567;0,25\n".encode(
        "cp1252"
    )
    assert parse_export_csv(decode_export(raw)) == [
        IleoReading(date(2026, 11, 3), index=1234567.0, consumption=250.0)
    ]


def test_separateur_virgule_et_tri() -> None:
    text = 'date,index\n"2026-11-02",10.5\n"2026-11-01",10.2\n'
    readings = parse_export_csv(text)
    assert [(r.day.day, r.index) for r in readings] == [(1, 10200.0), (2, 10500.0)]


@pytest.mark.parametrize(
    "text", ["", "<html>Erreur</html>", "Jour;Valeur\n01/11/2026;3\n"]
)
def test_entete_introuvable(text: str) -> None:
    with pytest.raises(IleoParseError):
        parse_export_csv(text)


def test_bom_utf8() -> None:
    raw = "﻿Date;Consommation (L)\n01/11/2026;12\n".encode()
    assert parse_export_csv(decode_export(raw))[0].consumption == 12.0
