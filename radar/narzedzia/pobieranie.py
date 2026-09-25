"""Pobieranie stron: cache na dysku, robots.txt, tempo per host, User-Agent z kontaktem.

Wymaga zmiennej RADAR_KONTAKT (adres e-mail wstawiany do User-Agent).
"""
from __future__ import annotations

import os
import re
import time
import unicodedata
from datetime import datetime
from functools import lru_cache
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from radar import cache
from radar.typy import Firma, Strona

MAX_PODSTRON = 5
# ogólne nazwy podstron; słowa specyficzne dla zlecenia są w profil.podstrony
PODSTRONY_OGOLNE = ["o nas", "o firmie", "about", "kariera", "praca", "career", "jobs",
                    "kontakt", "contact", "oferta", "uslugi"]
ODSTEP_S = 2.0  # minimalny odstęp między zapytaniami do jednego hosta
_ostatnio: dict[str, float] = {}


class ZablokowanePrzezRobots(Exception):
    pass


def _user_agent() -> str:
    kontakt = os.environ.get("RADAR_KONTAKT")
    if not kontakt:
        raise RuntimeError("Ustaw RADAR_KONTAKT (adres e-mail do User-Agent), np. $env:RADAR_KONTAKT='ja@firma.pl'")
    return f"RadarBot/0.1 (+mailto:{kontakt})"


def _czekaj(host: str) -> None:
    pauza = _ostatnio.get(host, 0) + ODSTEP_S - time.monotonic()
    if pauza > 0:
        time.sleep(pauza)
    _ostatnio[host] = time.monotonic()


def _get(url: str) -> httpx.Response:
    _czekaj(urlsplit(url).netloc)
    return httpx.get(url, headers={"User-Agent": _user_agent()}, follow_redirects=True, timeout=30)


@lru_cache(maxsize=None)
def _robots(baza: str) -> RobotFileParser:
    rp = RobotFileParser()
    try:
        odp = _get(f"{baza}/robots.txt")
        rp.parse(odp.text.splitlines() if odp.status_code == 200 else [])
    except httpx.HTTPError:
        rp.parse([])  # brak robots.txt = wolno
    return rp


def pobierz(url: str) -> Strona:
    if (dane := cache.wczytaj("strony", url)) is not None:
        return Strona(**dane, z_cache=True)
    czesci = urlsplit(url)
    if czesci.scheme not in ("http", "https"):
        raise ValueError(f"Nieobsługiwany adres: {url}")
    if not _robots(f"{czesci.scheme}://{czesci.netloc}").can_fetch("RadarBot", url):
        raise ZablokowanePrzezRobots(url)
    odp = _get(url)
    strona = Strona(url=str(odp.url), status=odp.status_code, typ=odp.headers.get("content-type", ""),
                    tresc=odp.text, pobrano=datetime.now())
    if odp.status_code < 500 and odp.status_code != 429:  # błędy przejściowe nie idą do cache
        cache.zapisz("strony", url, strona.model_dump(mode="json", exclude={"z_cache"}))
    return strona


def slowa(tekst: str) -> str:
    """Małe litery, same słowa oddzielone spacją — do porównań odpornych na formatowanie."""
    return " ".join(re.findall(r"\w+", tekst.lower()))


def _ascii(tekst: str) -> str:
    tekst = unicodedata.normalize("NFKD", tekst.lower().replace("ł", "l"))
    return slowa("".join(c for c in tekst if not unicodedata.combining(c)))


def domena(www: str | None) -> str | None:
    if not www:
        return None
    return urlsplit(www if "//" in www else f"//{www}").netloc.lower().removeprefix("www.") or None


def tekst_i_linki(strona: Strona) -> tuple[str, list[tuple[str, str]]]:
    """Tekst strony i linki (url, opis). Dla nie-HTML: surowa treść, bez linków."""
    if "html" not in strona.typ:
        return strona.tresc, []
    soup = BeautifulSoup(strona.tresc, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    linki = {}
    for a in soup.find_all("a", href=True):
        linki.setdefault(urljoin(strona.url, a["href"]).split("#")[0], a.get_text(" ", strip=True))
    return soup.get_text(" ", strip=True), [(u, t) for u, t in linki.items() if u.startswith("http")]


def pobierz_strony(firma: Firma, podstrony: list[str] = ()) -> list[Strona]:
    """Strona główna, adres z Places i do MAX_PODSTRON podstron, których link pasuje do słów."""
    if not firma.www:
        return []
    www = firma.www if "//" in firma.www else f"https://{firma.www}"
    cz = urlsplit(www)
    start = [f"{cz.scheme}://{cz.netloc}/", f"{cz.scheme}://{cz.netloc}{cz.path or '/'}"]  # bez ?utm_...
    strony = {}
    for url in dict.fromkeys(start):
        try:
            strony[url] = pobierz(url)
        except Exception:  # robots, timeout, DNS — firma zostaje z tym, co się udało
            pass
    klucze = [_ascii(k) for k in [*PODSTRONY_OGOLNE, *podstrony]]
    kandydaci = {}
    for s in list(strony.values()):
        for url, opis in tekst_i_linki(s)[1]:
            if domena(url) != domena(www) or url in strony:
                continue
            tekst = _ascii(f"{urlsplit(url).path} {opis}")
            if trafien := sum(k in tekst for k in klucze):
                kandydaci[url] = max(kandydaci.get(url, 0), trafien)
    for url in sorted(kandydaci, key=lambda u: (-kandydaci[u], len(u)))[:MAX_PODSTRON]:
        try:
            strony[url] = pobierz(url)
        except Exception:
            pass
    return [s for s in strony.values() if s.status == 200]
