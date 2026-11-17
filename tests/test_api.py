"""Tests du client Iléo contre des pages HYPOTHÉTIQUES (aucun accès réseau)."""

from __future__ import annotations

from datetime import date

import aiohttp
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ileo.api import IleoClient, is_login_page, parse_form
from custom_components.ileo.models import (
    IleoAuthError,
    IleoConnectionError,
    IleoResponseError,
)

from .conftest import load_fixture, load_fixture_bytes

BASE = "https://www.mel-ileo.fr"
LOGIN_URL = f"{BASE}/connexion.aspx"
CONSO_URL = f"{BASE}/espaceperso/mes-consommations.aspx"
HOME_HTML = "<html><body><form action='./accueil.aspx'></form>Bienvenue</body></html>"
CSV_HEADERS = {"Content-Type": "text/csv; charset=utf-8"}


@pytest.fixture
def client(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> IleoClient:
    session = aioclient_mock.create_session(hass.loop)
    return IleoClient(session, "abonne@example.com", "secret")


def _posted(aioclient_mock: AiohttpClientMocker, url: str) -> dict:
    return next(
        data
        for method, called_url, data, _ in aioclient_mock.mock_calls
        if method.lower() == "post" and str(called_url) == url
    )


def test_parse_form() -> None:
    form = parse_form(load_fixture("page_connexion_hypothetique.html"))
    assert form is not None
    assert form.action == "./connexion.aspx"
    # Les entités HTML sont décodées, seuls les champs cachés sont gardés.
    assert form.fields == {
        "__VIEWSTATE": "VS&login==",
        "__VIEWSTATEGENERATOR": "ABCD1234",
        "__EVENTVALIDATION": "EV-login",
    }
    assert parse_form("<html></html>") is None


def test_is_login_page() -> None:
    assert is_login_page(load_fixture("page_connexion_hypothetique.html"))
    assert not is_login_page(load_fixture("page_consommations_hypothetique.html"))


async def test_login_ok(
    client: IleoClient, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(LOGIN_URL, text=load_fixture("page_connexion_hypothetique.html"))
    aioclient_mock.post(LOGIN_URL, text=HOME_HTML)

    await client.async_login()

    data = _posted(aioclient_mock, LOGIN_URL)
    site = client.site
    assert data["__VIEWSTATE"] == "VS&login=="
    assert data["__EVENTVALIDATION"] == "EV-login"
    assert data[site.login_field] == "abonne@example.com"
    assert data[site.password_field] == "secret"


async def test_login_refuse(
    client: IleoClient, aioclient_mock: AiohttpClientMocker
) -> None:
    page = load_fixture("page_connexion_hypothetique.html")
    aioclient_mock.get(LOGIN_URL, text=page)
    aioclient_mock.post(
        LOGIN_URL, text=page.replace("<form", "Identifiants invalides<form")
    )
    with pytest.raises(IleoAuthError):
        await client.async_login()


async def test_login_sans_formulaire(
    client: IleoClient, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(LOGIN_URL, text="<html>Maintenance</html>")
    with pytest.raises(IleoResponseError):
        await client.async_login()


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"exc": aiohttp.ClientConnectionError()}, IleoConnectionError),
        ({"exc": TimeoutError()}, IleoConnectionError),
        ({"status": 503}, IleoConnectionError),
        ({"status": 404}, IleoResponseError),
    ],
)
async def test_erreurs_reseau(
    client: IleoClient, aioclient_mock: AiohttpClientMocker, kwargs, error
) -> None:
    aioclient_mock.get(LOGIN_URL, **kwargs)
    with pytest.raises(error):
        await client.async_login()


async def test_export(client: IleoClient, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(LOGIN_URL, text=load_fixture("page_connexion_hypothetique.html"))
    aioclient_mock.post(LOGIN_URL, text=HOME_HTML)
    aioclient_mock.get(
        CONSO_URL, text=load_fixture("page_consommations_hypothetique.html")
    )
    aioclient_mock.post(
        CONSO_URL,
        content=load_fixture_bytes("export_hypothetique.csv"),
        headers=CSV_HEADERS,
    )

    readings = await client.async_get_readings(date(2026, 5, 1), date(2026, 11, 17))

    assert len(readings) == 5
    assert readings[-1].index == 124412.0
    data = _posted(aioclient_mock, CONSO_URL)
    site = client.site
    assert data["__EVENTTARGET"] == site.export_event_target
    assert data["__VIEWSTATE"] == "VS-conso"
    assert data[site.export_start_field] == "01/05/2026"
    assert data[site.export_end_field] == "17/11/2026"


async def test_export_renvoie_du_html(
    client: IleoClient, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(LOGIN_URL, text=load_fixture("page_connexion_hypothetique.html"))
    aioclient_mock.post(LOGIN_URL, text=HOME_HTML)
    aioclient_mock.get(
        CONSO_URL, text=load_fixture("page_consommations_hypothetique.html")
    )
    aioclient_mock.post(
        CONSO_URL, text="<html>Erreur</html>", headers={"Content-Type": "text/html"}
    )
    with pytest.raises(IleoResponseError):
        await client.async_fetch_export(date(2026, 5, 1), date(2026, 11, 17))


async def test_session_expiree_reconnexion(
    client: IleoClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """La page des consommations redirige vers la connexion : on se reconnecte."""
    login_page = load_fixture("page_connexion_hypothetique.html")
    aioclient_mock.get(LOGIN_URL, text=login_page)
    aioclient_mock.post(LOGIN_URL, text=HOME_HTML)
    aioclient_mock.get(CONSO_URL, text=login_page)

    with pytest.raises(IleoAuthError):
        await client.async_fetch_export(date(2026, 5, 1), date(2026, 11, 17))
    # Connexion initiale + une seule reconnexion.
    logins = [c for c in aioclient_mock.mock_calls if c[0].lower() == "post"]
    assert len(logins) == 2
