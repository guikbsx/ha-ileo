"""Tests of the Iléo client against anonymized excerpts of the portal (no network)."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from datetime import date

import aiohttp
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.ileo.api import (
    MAX_REDIRECTS,
    MAX_RESPONSE_BYTES,
    IleoClient,
    is_login_page,
    parse_contracts,
)
from custom_components.ileo.models import (
    IleoAuthError,
    IleoConnectionError,
    IleoContract,
    IleoResponseError,
)

from .conftest import (
    CONTRACT,
    EMAIL,
    OTHER_CONTRACT,
    PASSWORD,
    load_fixture,
    load_fixture_bytes,
)

BASE = "https://www.mel-ileo.fr"
LOGIN_URL = f"{BASE}/connexion.aspx"
DASHBOARD_URL = f"{BASE}/espaceperso/tableau-de-bord.aspx"
EXPORT_URL = f"{BASE}/espaceperso/mes-consommations.aspx"
HTML = {"Content-Type": "text/html; charset=utf-8"}
CSV = {
    "Content-Type": "text/csv; charset=utf-8",
    "Content-Disposition": "attachment;filename=export.csv",
}
START, END = date(2026, 5, 27), date(2026, 11, 23)

type ClientFactory = Callable[..., IleoClient]


@pytest.fixture
async def make_client(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> AsyncGenerator[ClientFactory]:
    session = aioclient_mock.create_session(hass.loop)

    def factory(contract: str | None = None) -> IleoClient:
        return IleoClient(session, EMAIL, PASSWORD, contract=contract)

    yield factory
    await session.close()


@pytest.fixture
def client(make_client: ClientFactory) -> IleoClient:
    return make_client()


def _redirect(location: str, status: int = 302) -> dict:
    return {"status": status, "headers": {"Location": location}}


def _dashboard(selected: str | None, *numbers: str) -> str:
    """Build a dashboard page with the given contracts."""
    options = "".join(
        f'<option {"selected" if number == selected else ""} value="{number}">'
        f"{number} - Home</option>"
        for number in numbers
    )
    return f'<html><form method="POST"><select name="switchAbt">{options}</select></form></html>'


def _mock_login(
    aioclient_mock: AiohttpClientMocker, dashboard: str | None = None
) -> None:
    """Accepted sign-in: the portal redirects to the dashboard."""
    aioclient_mock.post(LOGIN_URL, **_redirect("espaceperso/tableau-de-bord.aspx"))
    aioclient_mock.get(
        DASHBOARD_URL,
        text=dashboard or load_fixture("dashboard_page.html"),
        headers=HTML,
    )


def _calls(aioclient_mock: AiohttpClientMocker, method: str) -> list:
    return [c for c in aioclient_mock.mock_calls if c[0].lower() == method]


# --- Page parsing -------------------------------------------------------------


def test_is_login_page() -> None:
    assert is_login_page(load_fixture("login_page.html"))
    assert not is_login_page(load_fixture("dashboard_page.html"))


def test_parse_contracts_real_page() -> None:
    """Real layout: one option, "<number> - <label>", HTML entities decoded."""
    contracts, selected = parse_contracts(load_fixture("dashboard_page.html"))
    assert contracts == [IleoContract(CONTRACT, "Maison & jardin")]
    assert selected == CONTRACT


def test_parse_contracts_several() -> None:
    contracts, selected = parse_contracts(
        load_fixture("dashboard_page_two_contracts.html")
    )
    assert contracts == [
        IleoContract(CONTRACT, "Maison & jardin"),
        IleoContract(OTHER_CONTRACT, ""),
    ]
    assert selected == CONTRACT


@pytest.mark.parametrize(
    ("html", "contracts", "selected"),
    [
        # No selector: the "Contrat n°…" line is used instead.
        ("<p>Contrat n°7654321</p>", [IleoContract(OTHER_CONTRACT)], OTHER_CONTRACT),
        # A single contract is the selected one even if the portal does not say so.
        (_dashboard(None, CONTRACT), [IleoContract(CONTRACT, "Home")], CONTRACT),
        # Several contracts and none marked as selected: unknown.
        (
            _dashboard(None, CONTRACT, OTHER_CONTRACT),
            [IleoContract(CONTRACT, "Home"), IleoContract(OTHER_CONTRACT, "Home")],
            None,
        ),
        # Options without a closing tag or without a value.
        (
            '<select name="switchAbt"><option value=""><option selected value="42">42'
            '</select><select name="other"><option value="9">9</option></select>',
            [IleoContract("42")],
            "42",
        ),
        ("<html>Bienvenue</html>", [], None),
    ],
)
def test_parse_contracts_variants(
    html: str, contracts: list[IleoContract], selected: str | None
) -> None:
    assert parse_contracts(html) == (contracts, selected)


# --- Sign-in ------------------------------------------------------------------


async def test_login_ok(
    client: IleoClient, aioclient_mock: AiohttpClientMocker
) -> None:
    _mock_login(aioclient_mock)

    assert await client.async_login() == [IleoContract(CONTRACT, "Maison & jardin")]

    (post,) = _calls(aioclient_mock, "post")
    assert str(post[1]) == LOGIN_URL
    assert post[2] == {
        "email": EMAIL,
        "password": PASSWORD,
        "valider": "je me connecte",
    }
    # The redirect is followed with a body-less GET.
    (get,) = _calls(aioclient_mock, "get")
    assert str(get[1]) == DASHBOARD_URL
    assert get[2] is None


async def test_login_rejected(
    client: IleoClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Rejected credentials: the portal shows the sign-in form again."""
    aioclient_mock.post(LOGIN_URL, text=load_fixture("login_page.html"), headers=HTML)
    with pytest.raises(IleoAuthError):
        await client.async_login()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"text": "<html>Site en maintenance</html>", "headers": HTML},
        _redirect("/erreur.aspx"),
        # The customer area, but without any contract.
        _redirect("/espaceperso/vide.aspx"),
    ],
)
async def test_login_without_proof(
    client: IleoClient, aioclient_mock: AiohttpClientMocker, kwargs: dict
) -> None:
    """A page that is neither the form nor a customer area with a contract is a failure."""
    aioclient_mock.post(LOGIN_URL, **kwargs)
    aioclient_mock.get(f"{BASE}/erreur.aspx", text="<html>Erreur</html>", headers=HTML)
    aioclient_mock.get(
        f"{BASE}/espaceperso/vide.aspx", text="<html>Bienvenue</html>", headers=HTML
    )

    with pytest.raises(IleoResponseError):
        await client.async_login()
    # Nothing is remembered: the next export signs in again.
    with pytest.raises(IleoResponseError):
        await client.async_fetch_export(START, END)
    assert len(_calls(aioclient_mock, "post")) == 2


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"exc": aiohttp.ClientConnectionError()}, IleoConnectionError),
        ({"exc": TimeoutError()}, IleoConnectionError),
        ({"status": 503}, IleoConnectionError),
        ({"status": 404}, IleoResponseError),
        (_redirect(""), IleoResponseError),
    ],
)
async def test_network_errors(
    client: IleoClient, aioclient_mock: AiohttpClientMocker, kwargs, error
) -> None:
    aioclient_mock.post(LOGIN_URL, **kwargs)
    with pytest.raises(error):
        await client.async_login()


# --- Safeguards ---------------------------------------------------------------


@pytest.mark.parametrize(
    "location",
    [
        "https://example.com/connexion.aspx",
        "http://www.mel-ileo.fr/connexion.aspx",
        "https://www.mel-ileo.fr.example.com/",
        "//example.com/",
        "mailto:contact@example.com",
        "http://[invalid",
    ],
)
async def test_redirect_outside_portal_refused(
    client: IleoClient, aioclient_mock: AiohttpClientMocker, location: str
) -> None:
    """No request ever leaves for anything but the portal over HTTPS."""
    aioclient_mock.post(LOGIN_URL, **_redirect(location, status=307))

    with pytest.raises(IleoResponseError):
        await client.async_login()
    assert [str(c[1]) for c in aioclient_mock.mock_calls] == [LOGIN_URL]


async def test_password_never_sent_again_on_redirect(
    client: IleoClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Even a 307/308 (which keeps the body) is followed with a body-less GET."""
    aioclient_mock.post(LOGIN_URL, **_redirect("/espaceperso/autre.aspx", status=307))
    aioclient_mock.get(
        f"{BASE}/espaceperso/autre.aspx",
        text=load_fixture("dashboard_page.html"),
        headers=HTML,
    )

    await client.async_login()

    assert len(_calls(aioclient_mock, "post")) == 1
    assert _calls(aioclient_mock, "get")[0][2] is None


async def test_too_many_redirects(
    client: IleoClient, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(LOGIN_URL, **_redirect("/boucle.aspx"))
    aioclient_mock.get(f"{BASE}/boucle.aspx", **_redirect("/boucle.aspx"))

    with pytest.raises(IleoResponseError):
        await client.async_login()
    assert len(_calls(aioclient_mock, "get")) == MAX_REDIRECTS


async def test_response_too_large(
    client: IleoClient, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(LOGIN_URL, content=b"x" * (MAX_RESPONSE_BYTES + 1))
    with pytest.raises(IleoResponseError):
        await client.async_login()


# --- Contracts ----------------------------------------------------------------


async def test_expected_contract_already_selected(
    make_client: ClientFactory, aioclient_mock: AiohttpClientMocker
) -> None:
    _mock_login(aioclient_mock, _dashboard(CONTRACT, CONTRACT, OTHER_CONTRACT))

    await make_client(CONTRACT).async_login()

    assert len(_calls(aioclient_mock, "post")) == 1


async def test_expected_contract_selected_on_the_portal(
    make_client: ClientFactory, aioclient_mock: AiohttpClientMocker
) -> None:
    """The portal shows another contract: the client switches before going on."""
    _mock_login(aioclient_mock, _dashboard(CONTRACT, CONTRACT, OTHER_CONTRACT))
    aioclient_mock.post(
        DASHBOARD_URL,
        text=_dashboard(OTHER_CONTRACT, CONTRACT, OTHER_CONTRACT),
        headers=HTML,
    )

    await make_client(OTHER_CONTRACT).async_login()

    switch = _calls(aioclient_mock, "post")[-1]
    assert str(switch[1]) == DASHBOARD_URL
    assert switch[2] == {"switchAbt": OTHER_CONTRACT}


async def test_contract_switch_not_applied(
    make_client: ClientFactory, aioclient_mock: AiohttpClientMocker
) -> None:
    """Without confirmation of the switch, no export is ever fetched."""
    page = _dashboard(CONTRACT, CONTRACT, OTHER_CONTRACT)
    _mock_login(aioclient_mock, page)
    aioclient_mock.post(DASHBOARD_URL, text=page, headers=HTML)

    with pytest.raises(IleoResponseError):
        await make_client(OTHER_CONTRACT).async_fetch_export(START, END)
    assert all(str(c[1]) != EXPORT_URL for c in _calls(aioclient_mock, "get"))


async def test_contract_no_longer_attached(
    make_client: ClientFactory, aioclient_mock: AiohttpClientMocker
) -> None:
    _mock_login(aioclient_mock)

    with pytest.raises(IleoResponseError):
        await make_client(OTHER_CONTRACT).async_login()
    assert len(_calls(aioclient_mock, "post")) == 1


async def test_selected_contract_unknown(
    client: IleoClient, aioclient_mock: AiohttpClientMocker
) -> None:
    _mock_login(aioclient_mock, _dashboard(None, CONTRACT, OTHER_CONTRACT))
    with pytest.raises(IleoResponseError):
        await client.async_login()


# --- Export -------------------------------------------------------------------


async def test_export(client: IleoClient, aioclient_mock: AiohttpClientMocker) -> None:
    _mock_login(aioclient_mock)
    aioclient_mock.get(
        EXPORT_URL,
        content=load_fixture_bytes("export_real_anonymized.csv"),
        headers=CSV,
    )

    readings = await client.async_get_readings(START, END)

    assert len(readings) == 5
    assert readings[-1].day == date(2026, 11, 22)
    assert readings[-1].index == 100603.0
    assert readings[-1].consumption == 182.0
    export_url = _calls(aioclient_mock, "get")[-1][1]
    assert export_url.path == URL(EXPORT_URL).path
    assert dict(export_url.query) == {
        "ex": "1",
        "dateDebut": "27/05/2026",
        "dateFin": "23/11/2026",
    }
    # Second export: the session is reused, no new sign-in.
    await client.async_fetch_export(START, END)
    assert len(_calls(aioclient_mock, "post")) == 1


async def test_export_returns_html(
    client: IleoClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Right after a successful sign-in, signing in again would be pointless."""
    _mock_login(aioclient_mock)
    aioclient_mock.get(EXPORT_URL, text="<html>Erreur</html>", headers=HTML)

    with pytest.raises(IleoResponseError):
        await client.async_fetch_export(START, END)
    assert len(_calls(aioclient_mock, "post")) == 1


def _mock_export_sequence(
    aioclient_mock: AiohttpClientMocker, *responses: dict
) -> None:
    """Successive responses of the export (the last one is repeated)."""
    remaining = list(responses)

    async def next_response(method, url, data) -> AiohttpClientMockResponse:
        kwargs = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return AiohttpClientMockResponse(method, url, **kwargs)

    aioclient_mock.get(EXPORT_URL, side_effect=next_response)


@pytest.mark.parametrize(
    "expired",
    [
        _redirect("../connexion.aspx"),
        # The portal may also answer with a page that has no password field.
        {"text": "<html>Bienvenue</html>", "headers": HTML},
    ],
)
async def test_expired_session_signs_in_again(
    client: IleoClient, aioclient_mock: AiohttpClientMocker, expired: dict
) -> None:
    """A page instead of the file: sign in again and retry."""
    csv = {
        "response": load_fixture_bytes("export_real_anonymized.csv"),
        "headers": CSV,
    }
    _mock_login(aioclient_mock)
    aioclient_mock.get(LOGIN_URL, text=load_fixture("login_page.html"), headers=HTML)
    _mock_export_sequence(aioclient_mock, csv, expired, csv)

    await client.async_fetch_export(START, END)
    assert len(_calls(aioclient_mock, "post")) == 1

    assert len(await client.async_get_readings(START, END)) == 5
    assert len(_calls(aioclient_mock, "post")) == 2


async def test_export_refused_after_signing_in_again(
    client: IleoClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A single retry; the failure is not reported as a password problem."""
    csv = {
        "response": load_fixture_bytes("export_real_anonymized.csv"),
        "headers": CSV,
    }
    _mock_login(aioclient_mock)
    aioclient_mock.get(LOGIN_URL, text=load_fixture("login_page.html"), headers=HTML)
    _mock_export_sequence(aioclient_mock, csv, _redirect("../connexion.aspx"))

    await client.async_fetch_export(START, END)
    with pytest.raises(IleoResponseError) as excinfo:
        await client.async_fetch_export(START, END)
    assert not isinstance(excinfo.value, IleoAuthError)
    assert len(_calls(aioclient_mock, "post")) == 2

    # The session must be renewed: the next call signs in again.
    with pytest.raises(IleoResponseError):
        await client.async_fetch_export(START, END)
    assert len(_calls(aioclient_mock, "post")) == 3
