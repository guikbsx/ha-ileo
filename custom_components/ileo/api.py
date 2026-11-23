"""Client for the Iléo customer area (https://www.mel-ileo.fr).

This module does not depend on Home Assistant: it is given an `aiohttp` session
(with its own cookie jar) and offers three operations:

- `async_login()`: sign in and list the contracts of the account;
- `async_fetch_export(start, end)`: download the raw CSV export;
- `async_get_readings(start, end)`: download the export and parse it.

Behaviour observed on the portal (November 2026):

- sign-in: POST `email`, `password` and `valider` to `/connexion.aspx`; on
  success the portal redirects to the customer area (`/espaceperso/…`),
  otherwise it shows the sign-in form again;
- contracts: the customer area shows a `<select name="switchAbt">` whose option
  values are the contract numbers; the selected one is the contract the other
  pages (and the export) are about;
- export: GET
  `/espaceperso/mes-consommations.aspx?ex=1&dateDebut=DD/MM/YYYY&dateFin=DD/MM/YYYY`,
  which returns a `text/csv` file (see `parser.py`);
- expired session: the export returns an HTML page instead of the file.

Safeguards (see `IleoClient._request`):

- credentials are only ever sent to `BASE_URL`, over HTTPS; a redirect to any
  other origin is refused;
- a redirect is always followed with a body-less GET: the password is never
  sent a second time;
- response size and redirect count are capped;
- the export is only fetched once the portal confirms that the expected
  contract is selected, so data never lands in another contract's statistics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
import logging
import re

import aiohttp
from yarl import URL

from .models import (
    IleoAuthError,
    IleoConnectionError,
    IleoContract,
    IleoReading,
    IleoResponseError,
)
from .parser import decode_export, parse_export_csv

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://www.mel-ileo.fr"
LOGIN_PATH = "/connexion.aspx"
MEMBER_AREA_PATH = "/espaceperso/"
EXPORT_PATH = "/espaceperso/mes-consommations.aspx"
EXPORT_DATE_FORMAT = "%d/%m/%Y"
CONTRACT_FIELD = "switchAbt"
USER_AGENT = "HomeAssistant-Ileo/0.1 (+https://github.com/guikbsx/ha-ileo)"

DEFAULT_TIMEOUT = 60
"""Maximum duration of a request, in seconds."""
MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
"""Response size cap (a portal page weighs about 80 kB)."""

_ORIGIN = URL(BASE_URL).origin()
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_READ_CHUNK_BYTES = 64 * 1024
_PASSWORD_INPUT_RE = re.compile(r"<input[^>]+type\s*=\s*[\"']?password", re.IGNORECASE)
_CONTRACT_NUMBER_RE = re.compile(r"Contrat\s+n°\s*(\w+)")


def is_login_page(html: str) -> bool:
    """A page with a password field is (still) the sign-in page."""
    return _PASSWORD_INPUT_RE.search(html) is not None


class _ContractParser(HTMLParser):
    """Collect the options of the contract selector of the customer area."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.contracts: list[IleoContract] = []
        self.selected: str | None = None
        self._in_selector = False
        self._option: tuple[str, bool] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "select":
            self._in_selector = attributes.get("name") == CONTRACT_FIELD
        elif tag == "option" and self._in_selector:
            self._close_option()
            number = (attributes.get("value") or "").strip()
            self._option = (number, "selected" in attributes)

    def handle_data(self, data: str) -> None:
        if self._option is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("option", "select"):
            self._close_option()
        if tag == "select":
            self._in_selector = False

    def _close_option(self) -> None:
        if self._option is None:
            return
        number, selected = self._option
        text = " ".join("".join(self._text).split())
        self._option = None
        self._text = []
        if not number:
            return
        # The portal labels an option "<number> - <name given by the subscriber>".
        label = text.removeprefix(number).lstrip(" -–")
        self.contracts.append(IleoContract(number, label))
        if selected:
            self.selected = number


def parse_contracts(html: str) -> tuple[list[IleoContract], str | None]:
    """Return the contracts of the account and the number of the selected one."""
    parser = _ContractParser()
    parser.feed(html)
    parser.close()
    contracts, selected = parser.contracts, parser.selected
    if not contracts and (match := _CONTRACT_NUMBER_RE.search(html)):
        # No selector: fall back on the "Contrat n°…" line of the dashboard.
        contracts = [IleoContract(match.group(1))]
    if selected is None and len(contracts) == 1:
        selected = contracts[0].number
    return contracts, selected


@dataclass(frozen=True, slots=True)
class _Response:
    url: URL
    """Final URL, after redirects."""
    content_type: str
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    @property
    def is_html(self) -> bool:
        return "html" in self.content_type.lower() or self.body.lstrip()[:1] == b"<"

    @property
    def is_login_page(self) -> bool:
        return self.is_html and is_login_page(self.text)


async def _read_capped(resp: aiohttp.ClientResponse) -> bytes:
    """Read the response body, refusing anything above `MAX_RESPONSE_BYTES`."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in resp.content.iter_chunked(_READ_CHUNK_BYTES):
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise IleoResponseError("Response from the portal is too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _redirect_target(url: URL, location: str) -> URL:
    """Return the target of a redirect, which must stay on the portal over HTTPS."""
    if not location:
        raise IleoResponseError("Redirect without a target")
    try:
        target = url.join(URL(location))
        same_origin = target.origin() == _ORIGIN
    except ValueError as err:
        raise IleoResponseError("Invalid redirect") from err
    if not same_origin:
        raise IleoResponseError("Redirect outside of the Iléo portal refused")
    return target


class IleoClient:
    """Access to the Iléo customer area of one subscriber.

    `contract` is the number of the contract to read. Without it, the client
    uses whichever contract the portal selects by default.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        *,
        contract: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._contract = contract
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._logged_in = False

    async def async_login(self) -> list[IleoContract]:
        """Sign in to the customer area and return the contracts of the account.

        Raises `IleoAuthError` if the portal shows the sign-in form again, and
        `IleoResponseError` if it answers with anything but the customer area
        (a maintenance page, for instance) or if the expected contract cannot
        be selected: without proof, the sign-in is not considered successful.
        """
        self._logged_in = False
        resp = await self._request(
            "POST",
            URL(BASE_URL).join(URL(LOGIN_PATH)),
            data={
                "email": self._email,
                "password": self._password,
                "valider": "je me connecte",
            },
        )
        if resp.is_login_page:
            raise IleoAuthError("Credentials rejected by the Iléo portal")
        if not resp.url.path.startswith(MEMBER_AREA_PATH):
            raise IleoResponseError("The portal did not open the customer area")

        contracts, selected = parse_contracts(resp.text)
        if not contracts:
            raise IleoResponseError("No contract found in the customer area")
        if self._contract is not None and selected != self._contract:
            selected = await self._async_select_contract(resp.url, contracts)
        if selected is None:
            raise IleoResponseError("Unable to tell which contract is selected")

        self._contract = selected
        self._logged_in = True
        _LOGGER.debug("Signed in to the Iléo customer area")
        return contracts

    async def _async_select_contract(
        self, url: URL, contracts: list[IleoContract]
    ) -> str:
        """Ask the portal to switch to the expected contract and check it did.

        The selector is a form posted to the page that shows it. This could not
        be tried on an account with several contracts, hence the strict check.
        """
        wanted = self._contract
        if wanted not in {contract.number for contract in contracts}:
            raise IleoResponseError("The contract is no longer attached to the account")
        resp = await self._request("POST", url, data={CONTRACT_FIELD: wanted})
        _, selected = parse_contracts(resp.text)
        if selected != wanted:
            raise IleoResponseError("The portal did not switch to the contract")
        return wanted

    async def async_fetch_export(self, start: date, end: date) -> bytes:
        """Download the raw consumption export between `start` and `end`."""
        url = (
            URL(BASE_URL)
            .join(URL(EXPORT_PATH))
            .with_query(
                {
                    "ex": "1",
                    "dateDebut": start.strftime(EXPORT_DATE_FORMAT),
                    "dateFin": end.strftime(EXPORT_DATE_FORMAT),
                }
            )
        )
        just_logged_in = not self._logged_in
        if just_logged_in:
            await self.async_login()

        resp = await self._request("GET", url)
        if resp.is_html and not just_logged_in:
            # A page instead of the file: the session has expired. Sign in again
            # once, whatever the page is.
            _LOGGER.debug("Iléo session expired, signing in again")
            await self.async_login()
            resp = await self._request("GET", url)

        if resp.is_html:
            # The credentials were just accepted, so this is not a password
            # problem; the session must be renewed on the next call though.
            self._logged_in = False
            raise IleoResponseError("The portal did not return an export file")
        return resp.body

    async def async_get_readings(self, start: date, end: date) -> list[IleoReading]:
        """Download and parse the export: daily readings sorted by day."""
        raw = await self.async_fetch_export(start, end)
        return parse_export_csv(decode_export(raw))

    async def _request(
        self, method: str, url: URL, data: dict[str, str] | None = None
    ) -> _Response:
        """Query the portal, following redirects by hand.

        aiohttp would follow a redirect to any host, and send the request body
        again on a 307/308. Here every hop is checked (see `_redirect_target`):
        same origin as `BASE_URL`, and always a body-less GET. The first URL is
        always built from `BASE_URL`.
        """
        for _ in range(MAX_REDIRECTS + 1):
            location: str | None = None
            body = b""
            try:
                async with self._session.request(
                    method,
                    url,
                    data=data,
                    headers={"User-Agent": USER_AGENT},
                    timeout=self._timeout,
                    allow_redirects=False,
                ) as resp:
                    status = resp.status
                    content_type = resp.headers.get("Content-Type", "")
                    if status in _REDIRECT_STATUSES:
                        location = resp.headers.get("Location", "")
                    elif status < 400:
                        body = await _read_capped(resp)
            except (aiohttp.ClientError, TimeoutError) as err:
                raise IleoConnectionError(
                    f"Iléo portal unreachable ({type(err).__name__})"
                ) from err

            if status >= 500:
                raise IleoConnectionError(f"Iléo server error (HTTP {status})")
            if status >= 400:
                raise IleoResponseError(f"Unexpected response (HTTP {status})")
            if location is None:
                return _Response(url, content_type, body)

            url = _redirect_target(url, location)
            method, data = "GET", None

        raise IleoResponseError("Too many redirects")
