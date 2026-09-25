"""Pobieranie stron: cache na dysku, robots.txt, tempo per host, User-Agent z kontaktem.

Wymaga zmiennej RADAR_KONTAKT (adres e-mail wstawiany do User-Agent).
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from functools import lru_cache
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from radar import cache
from radar.typy import Firma, Strona

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


def pobierz_strony(firma: Firma) -> list[Strona]:
    raise NotImplementedError
