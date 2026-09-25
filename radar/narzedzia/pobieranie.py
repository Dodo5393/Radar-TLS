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
PLIKI = re.compile(r"\.(pdf|docx?|xlsx?|pptx?|zip|rar|jpe?g|png|gif|webp|svg|mp4)$", re.I)
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


def _klucz(url: str) -> str:
    """Jedna podstrona = jeden klucz: bez www, ?zapytania i końcowego /."""
    return f"{domena(url)}{urlsplit(url).path.rstrip('/')}"


def pobierz_strony(firma: Firma, podstrony: list[str] = ()) -> list[Strona]:
    """Strona główna, adres z Places i do MAX_PODSTRON podstron HTML, których link pasuje do słów."""
    if not firma.www:
        return []
    www = firma.www if "//" in firma.www else f"https://{firma.www}"
    cz = urlsplit(www)
    strony: dict[str, Strona] = {}

    def dodaj(url: str) -> None:
        try:
            s = pobierz(url)
        except Exception:  # robots, timeout, DNS — firma zostaje z tym, co się udało
            return
        if s.status == 200 and "html" in s.typ:  # PDF-y i obrazki to śmieci w prompcie
            strony.setdefault(_klucz(s.url), s)  # po przekierowaniu może to być już znana strona

    for url in dict.fromkeys([f"{cz.scheme}://{cz.netloc}/", f"{cz.scheme}://{cz.netloc}{cz.path or '/'}"]):
        dodaj(url)
    klucze = [_ascii(k) for k in [*PODSTRONY_OGOLNE, *podstrony]]
    kandydaci: dict[str, tuple[int, str]] = {}
    for s in list(strony.values()):
        for url, opis in tekst_i_linki(s)[1]:
            k, sciezka = _klucz(url), urlsplit(url).path
            if domena(url) != domena(www) or k in strony or PLIKI.search(sciezka):
                continue
            trafien = sum(kl in _ascii(f"{sciezka} {opis}") for kl in klucze)
            if trafien > kandydaci.get(k, (0, ""))[0]:  # przy remisie zostaje pierwszy widziany adres
                kandydaci[k] = (trafien, url.split("?")[0])
    for _, url in sorted(kandydaci.values(), key=lambda t: (-t[0], len(t[1])))[:MAX_PODSTRON]:
        dodaj(url)
    return list(strony.values())
