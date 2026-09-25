"""Google Places API (New), Text Search. Wymaga GOOGLE_PLACES_API_KEY."""
from __future__ import annotations

import os

import httpx

from radar import cache
from radar.typy import Miejsce

URL = "https://places.googleapis.com/v1/places:searchText"
POLA = ("places.id,places.displayName,places.formattedAddress,places.websiteUri,"
        "places.nationalPhoneNumber,places.types,nextPageToken")
STRONY = 3  # API zwraca maks. 20 wyników na stronę, 60 łącznie
CACHE_DNI = 30  # warunki Google Maps Platform nie pozwalają trzymać treści Places dłużej


def szukaj_miejsca(fraza: str, obszar: str) -> list[Miejsce]:
    zapytanie = f"{fraza} {obszar}"
    if (dane := cache.wczytaj("places", zapytanie, CACHE_DNI)) is not None:
        return [Miejsce(**m) for m in dane]
    klucz = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not klucz:
        raise RuntimeError("Ustaw GOOGLE_PLACES_API_KEY")
    wyniki, token = [], None
    for _ in range(STRONY):
        cialo = {"textQuery": zapytanie, "languageCode": "pl", "regionCode": "PL", "pageSize": 20}
        if token:
            cialo["pageToken"] = token
        odp = httpx.post(URL, json=cialo, timeout=30,
                         headers={"X-Goog-Api-Key": klucz, "X-Goog-FieldMask": POLA})
        odp.raise_for_status()
        dane = odp.json()
        wyniki += [Miejsce(
            place_id=p["id"],
            nazwa=p.get("displayName", {}).get("text", ""),
            adres=p.get("formattedAddress", ""),
            www=p.get("websiteUri"),
            telefon=p.get("nationalPhoneNumber"),
            kategorie=p.get("types", []),
        ) for p in dane.get("places", [])]
        if not (token := dane.get("nextPageToken")):
            break
    cache.zapisz("places", zapytanie, [m.model_dump() for m in wyniki])
    return wyniki
