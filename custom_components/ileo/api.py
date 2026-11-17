"""Client de l'espace client Iléo (https://www.mel-ileo.fr).

Ce module ne dépend pas de Home Assistant : il reçoit une session `aiohttp`
(avec son propre stockage de cookies) et expose trois opérations :

- `async_login()` : connexion à l'espace client ;
- `async_fetch_export(start, end)` : téléchargement brut de l'export CSV ;
- `async_get_readings(start, end)` : export téléchargé puis interprété.

Le portail est une application ASP.NET WebForms : chaque formulaire contient des
champs cachés (`__VIEWSTATE`, `__EVENTVALIDATION`, …) qu'il faut renvoyer tels
quels avec la soumission.

⚠️ HYPOTHÈSES : les noms des champs de formulaire, le contrôle qui déclenche
l'export et les champs de dates ci-dessous n'ont pas encore été relevés sur le
vrai site (étape 2). Ils sont regroupés dans `IleoSiteConfig` pour être calés
sans toucher au reste du code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
import logging
import re
from typing import Any

import aiohttp
from yarl import URL

from .models import (
    IleoAuthError,
    IleoConnectionError,
    IleoReading,
    IleoResponseError,
)
from .parser import decode_export, parse_export_csv

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://www.mel-ileo.fr"
USER_AGENT = "HomeAssistant-Ileo/0.1 (+https://github.com/guikbsx/ha-ileo)"

_PASSWORD_INPUT_RE = re.compile(r"<input[^>]+type\s*=\s*[\"']?password", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class IleoSiteConfig:
    """Paramètres du portail susceptibles d'évoluer (à caler à l'étape 2)."""

    base_url: str = BASE_URL
    login_path: str = "/connexion.aspx"
    consumption_path: str = "/espaceperso/mes-consommations.aspx"

    # HYPOTHÈSE : champs du formulaire de connexion.
    login_field: str = "ctl00$ContentPlaceHolder1$txtLogin"
    password_field: str = "ctl00$ContentPlaceHolder1$txtPassword"
    login_submit: tuple[str, str] | None = (
        "ctl00$ContentPlaceHolder1$btnConnexion",
        "Se connecter",
    )

    # HYPOTHÈSE : postback WebForms qui déclenche l'export CSV.
    export_event_target: str = "ctl00$ContentPlaceHolder1$lnkExportCsv"
    export_submit: tuple[str, str] | None = None
    # HYPOTHÈSE : champs de période (None si le portail n'en a pas).
    export_start_field: str | None = "ctl00$ContentPlaceHolder1$txtDateDebut"
    export_end_field: str | None = "ctl00$ContentPlaceHolder1$txtDateFin"
    export_date_format: str = "%d/%m/%Y"
    extra_export_fields: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class WebForm:
    """Formulaire HTML : adresse d'envoi et champs pré-remplis (cachés)."""

    action: str | None
    fields: dict[str, str]


class _FormParser(HTMLParser):
    """Extrait le premier formulaire d'une page ASP.NET et ses champs cachés."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.form: WebForm | None = None
        self._in_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {k.lower(): v or "" for k, v in attrs}
        if tag == "form" and self.form is None:
            self.form = WebForm(action=attributes.get("action") or None, fields={})
            self._in_form = True
        elif tag == "input" and self._in_form and self.form is not None:
            name = attributes.get("name")
            if name and attributes.get("type", "text").lower() == "hidden":
                self.form.fields[name] = attributes.get("value", "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._in_form = False


def parse_form(html: str) -> WebForm | None:
    """Retourne le premier formulaire de la page, ou None."""
    parser = _FormParser()
    parser.feed(html)
    parser.close()
    return parser.form


def is_login_page(html: str) -> bool:
    """Une page contenant un champ mot de passe est (encore) la page de connexion."""
    return _PASSWORD_INPUT_RE.search(html) is not None


@dataclass(slots=True)
class _Response:
    url: URL
    status: int
    content_type: str
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class IleoClient:
    """Accès à l'espace client Iléo d'un abonné."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        *,
        site: IleoSiteConfig | None = None,
        timeout: float = 60,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._site = site or IleoSiteConfig()
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._logged_in = False

    @property
    def site(self) -> IleoSiteConfig:
        return self._site

    def _url(self, path: str) -> URL:
        return URL(self._site.base_url).join(URL(path))

    async def _request(
        self, method: str, url: URL, data: dict[str, str] | None = None
    ) -> _Response:
        try:
            async with self._session.request(
                method,
                url,
                data=data,
                headers={"User-Agent": USER_AGENT},
                timeout=self._timeout,
                allow_redirects=True,
            ) as resp:
                body = await resp.read()
                status = resp.status
                final_url = resp.url
                content_type = resp.headers.get("Content-Type", "")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise IleoConnectionError(f"Portail Iléo injoignable : {err}") from err

        if status >= 500:
            raise IleoConnectionError(f"Erreur serveur Iléo (HTTP {status})")
        if status >= 400:
            raise IleoResponseError(f"Réponse inattendue du portail (HTTP {status})")
        return _Response(final_url, status, content_type, body)

    @staticmethod
    def _form_or_raise(resp: _Response, what: str) -> tuple[WebForm, URL]:
        form = parse_form(resp.text)
        if form is None:
            raise IleoResponseError(f"Formulaire introuvable sur la page {what}")
        target = resp.url.join(URL(form.action)) if form.action else resp.url
        return form, target

    async def async_login(self) -> None:
        """Se connecte à l'espace client. Lève `IleoAuthError` si refusé."""
        site = self._site
        page = await self._request("GET", self._url(site.login_path))
        form, target = self._form_or_raise(page, "de connexion")

        data: dict[str, str] = {
            **form.fields,
            site.login_field: self._email,
            site.password_field: self._password,
        }
        if site.login_submit:
            data[site.login_submit[0]] = site.login_submit[1]

        resp = await self._request("POST", target, data=data)
        if is_login_page(resp.text):
            self._logged_in = False
            raise IleoAuthError("Identifiants refusés par le portail Iléo")
        self._logged_in = True
        _LOGGER.debug("Connecté à l'espace client Iléo")

    async def async_fetch_export(self, start: date, end: date) -> bytes:
        """Télécharge l'export brut des consommations entre `start` et `end`."""
        if not self._logged_in:
            await self.async_login()

        page = await self._request("GET", self._url(self._site.consumption_path))
        if is_login_page(page.text):
            # Session expirée : une seule nouvelle tentative.
            _LOGGER.debug("Session Iléo expirée, reconnexion")
            await self.async_login()
            page = await self._request("GET", self._url(self._site.consumption_path))
            if is_login_page(page.text):
                raise IleoAuthError("Session refusée après reconnexion")

        form, target = self._form_or_raise(page, "des consommations")
        resp = await self._request(
            "POST", target, data=self._export_data(form, start, end)
        )

        if "html" in resp.content_type.lower() or resp.body.lstrip()[:1] == b"<":
            if is_login_page(resp.text):
                self._logged_in = False
                raise IleoAuthError("Session perdue pendant l'export")
            raise IleoResponseError("Le portail n'a pas renvoyé de fichier d'export")
        return resp.body

    def _export_data(self, form: WebForm, start: date, end: date) -> dict[str, Any]:
        site = self._site
        data: dict[str, Any] = {
            **form.fields,
            "__EVENTTARGET": site.export_event_target,
            "__EVENTARGUMENT": "",
            **site.extra_export_fields,
        }
        if site.export_start_field:
            data[site.export_start_field] = start.strftime(site.export_date_format)
        if site.export_end_field:
            data[site.export_end_field] = end.strftime(site.export_date_format)
        if site.export_submit:
            data[site.export_submit[0]] = site.export_submit[1]
        return data

    async def async_get_readings(self, start: date, end: date) -> list[IleoReading]:
        """Télécharge et interprète l'export : relevés journaliers triés."""
        raw = await self.async_fetch_export(start, end)
        return parse_export_csv(decode_export(raw))
